
import {
    forwardRef,
    useEffect,
    useImperativeHandle,
    useRef,
    useState,
} from "react";

import {
    initializeFaceDetector,
    detectFaces,
} from "./AIProctor";

import {
    initializePhoneDetector,
    detectPhone,
} from "./PhoneDetector";

type ExamCameraProps = {
    sessionId: string;
    token: string;
    clientId: string;
    autoStart?: boolean;
    initialStream?: MediaStream | null;
    onReadyChange?: (ready: boolean) => void;
    onRecordingChange?: (active: boolean) => void;
};

export type ExamCameraHandle = {
    finishRecording: () => Promise<boolean>;
};

const API =
    (import.meta as any).env?.VITE_API_BASE_URL ||
    "http://127.0.0.1:8000";

const CHUNK_INTERVAL_MS = 10_000;
const MAX_TEST_BYTES = 25 * 1024 * 1024;
const MAX_CHUNK_BYTES = 5 * 1024 * 1024;
const MAX_PENDING_UPLOADS = 6;

function selectMimeType(): string {
    const formats = [
        "video/webm;codecs=vp8,opus",
        "video/webm",
        "video/mp4",
    ];

    return (
        formats.find((type) =>
            MediaRecorder.isTypeSupported(type)
        ) || ""
    );
}

function delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}


function playFaceWarningTone() {
    try {
        const context = new AudioContext();
        const oscillator = context.createOscillator();
        const gain = context.createGain();

        oscillator.type = "sine";
        oscillator.frequency.value = 660;

        oscillator.connect(gain);
        gain.connect(context.destination);

        const now = context.currentTime;

        gain.gain.setValueAtTime(0.0001, now);
        gain.gain.exponentialRampToValueAtTime(0.08, now + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.28);

        oscillator.start(now);
        oscillator.stop(now + 0.3);

        oscillator.onended = () => {
            void context.close();
        };
    } catch (error) {
        console.warn("Warning sound unavailable:", error);
    }
}



const ExamCamera = forwardRef<ExamCameraHandle, ExamCameraProps>(function ExamCamera({
    sessionId,
    token,
    clientId,
    autoStart = false,
    initialStream = null,
    onReadyChange,
    onRecordingChange,
}: ExamCameraProps, ref) {
    const videoRef = useRef<HTMLVideoElement>(null);
    const streamRef = useRef<MediaStream | null>(null);
    const recorderRef = useRef<MediaRecorder | null>(null);
    const chunksRef = useRef<Blob[]>([]);
    const bytesRef = useRef(0);
    const sequenceRef = useRef(0);
    const pendingRef = useRef(0);
    const failedRef = useRef(0);
    const uploadQueueRef = useRef<Promise<void>>(
        Promise.resolve()
    );
    const downloadUrlRef = useRef<string | null>(null);
    const mountedRef = useRef(false);
    const recordingStartedRef = useRef(false);
    const backupTruncatedRef = useRef(false);

    const [cameraReady, setCameraReady] = useState(false);
    const [aiFaceStatus, setAiFaceStatus] = useState(
        "AI face detection initializing..."
    );
    const [faceWarningSeconds, setFaceWarningSeconds] =
        useState<number | null>(null);

    const [faceWarningVisible, setFaceWarningVisible] =
        useState(false);

    const faceWarningShownAtRef = useRef<number | null>(null);

    const [, setPhoneStatus] =
        useState("Phone detection initializing...");
    const [phoneAlert, setPhoneAlert] = useState(false);
    const phoneAlertUntilRef = useRef(0);
    const [starting, setStarting] = useState(false);
    const [recording, setRecording] = useState(false);
    const [finalizing, setFinalizing] = useState(false);

    const [, setChunkCount] = useState(0);
    const [, setUploadedCount] = useState(0);
    const [, setPendingCount] = useState(0);
    const [failedCount, setFailedCount] = useState(0);

    const [downloadUrl, setDownloadUrl] = useState("");
    const [extension, setExtension] = useState("webm");
    const [error, setError] = useState("");
    const [, setNotice] = useState("");

    function resetRecording() {
        if (downloadUrlRef.current) {
            URL.revokeObjectURL(downloadUrlRef.current);
            downloadUrlRef.current = null;
        }

        chunksRef.current = [];
        bytesRef.current = 0;
        backupTruncatedRef.current = false;
        sequenceRef.current = 0;
        pendingRef.current = 0;
        failedRef.current = 0;
        uploadQueueRef.current = Promise.resolve();

        setChunkCount(0);
        setUploadedCount(0);
        setPendingCount(0);
        setFailedCount(0);
        setDownloadUrl("");
        setNotice("");
    }

    function stopRecording() {
        const recorder = recorderRef.current;

        if (recorder && recorder.state === "recording") {
            setFinalizing(true);
            recorder.stop();
        }
    }


    async function finishRecording(): Promise<boolean> {
        try {
            const recorder = recorderRef.current;

            if (!recorder || !recordingStartedRef.current) {
                return false;
            }

            if (recorder.state !== "inactive") {
                const stopped = new Promise<void>((resolve) => {
                    recorder.addEventListener("stop", () => resolve(), {
                        once: true,
                    });
                });

                stopRecording();
                await stopped;
            }

            // Wait for every chunk, including the final one.
            await uploadQueueRef.current;

            return (
                failedRef.current === 0 &&
                pendingRef.current === 0
            );
        } catch (error) {
            console.error("Recording finalization failed:", error);
            return false;
        }
    }

    useImperativeHandle(ref, () => ({
        finishRecording,
    }));


    async function uploadChunk(
        blob: Blob,
        sequence: number,
        mimeType: string
    ): Promise<void> {
        if (blob.size > MAX_CHUNK_BYTES) {
            throw new Error(
                `Chunk ${sequence} exceeds the backend 5 MB limit`
            );
        }

        const form = new FormData();
        const fileExtension = mimeType.includes("mp4")
            ? "mp4"
            : "webm";

        form.append("sequence", String(sequence));
        form.append(
            "chunk",
            new Blob([blob], { type: mimeType }),
            `chunk_${String(sequence).padStart(6, "0")}.${fileExtension}`
        );

        let lastError: Error | null = null;

        for (let attempt = 1; attempt <= 3; attempt++) {
            try {
                const response = await fetch(
                    `${API}/api/exams/${encodeURIComponent(sessionId)}/recordings/chunks`,
                    {
                        method: "POST",
                        headers: {
                            Authorization: `Bearer ${token}`,
                            "X-Exam-Client": clientId,
                        },
                        body: form,
                    }
                );

                if (!response.ok) {
                    const body = await response.text();

                    // Don't retry authorization or session errors.
                    if (
                        [400, 401, 403, 409, 413, 415, 422].includes(
                            response.status
                        )
                    ) {
                        throw new Error(
                            `Upload rejected (${response.status}): ${body}`
                        );
                    }

                    throw new Error(
                        `Upload failed (${response.status}): ${body}`
                    );
                }

                const data = await response.json();

                if (data.stored !== true) {
                    throw new Error(
                        "Server did not confirm recording storage"
                    );
                }

                return;
            } catch (caught) {
                lastError =
                    caught instanceof Error
                        ? caught
                        : new Error(String(caught));

                // Permanent errors should be reported immediately.
                if (lastError.message.includes("Upload rejected")) {
                    break;
                }

                if (attempt < 3) {
                    await delay(attempt * 1000);
                }
            }
        }

        throw lastError || new Error("Unknown upload failure");
    }

    function queueChunk(
        blob: Blob,
        sequence: number,
        mimeType: string
    ) {
        if (pendingRef.current >= MAX_PENDING_UPLOADS) {
            failedRef.current += 1;
            setFailedCount(failedRef.current);

            setError(
                "Recording uploads cannot keep up. " +
                "Recording stopped to prevent unlimited memory use."
            );

            stopRecording();
            return;
        }

        pendingRef.current += 1;
        setPendingCount(pendingRef.current);

        uploadQueueRef.current = uploadQueueRef.current.then(
            async () => {
                try {
                    await uploadChunk(blob, sequence, mimeType);

                    if (mountedRef.current) {
                        setUploadedCount((count) => count + 1);
                    }
                } catch (caught) {
                    failedRef.current += 1;

                    console.error(
                        `Recording chunk ${sequence} failed:`,
                        caught
                    );

                    if (mountedRef.current) {
                        setFailedCount(failedRef.current);
                        setError(
                            `Recording chunk ${sequence} could not be uploaded. ` +
                            "Keep the local download as a backup."
                        );
                    }
                } finally {
                    pendingRef.current -= 1;

                    if (mountedRef.current) {
                        setPendingCount(pendingRef.current);
                    }
                }
            }
        );
    }

    async function startCamera() {
        if (starting || streamRef.current) return;

        if (
            !navigator.mediaDevices?.getUserMedia ||
            typeof MediaRecorder === "undefined"
        ) {
            setError("Browser recording APIs are unavailable.");
            return;
        }

        setStarting(true);
        setError("");

        try {
            const stream = initialStream &&
                initialStream.getVideoTracks().some(t => t.readyState === "live") &&
                initialStream.getAudioTracks().some(t => t.readyState === "live")
                ? initialStream
                : await navigator.mediaDevices.getUserMedia({
                    video: {
                        width: { ideal: 640 },
                        height: { ideal: 360 },
                        frameRate: { ideal: 15, max: 20 },
                    },
                    audio: {
                        echoCancellation: true,
                        noiseSuppression: true,
                    },
                });

            if (!mountedRef.current) {
                stream.getTracks().forEach((track) => track.stop());
                return;
            }

            streamRef.current = stream;

            if (videoRef.current) {
                videoRef.current.srcObject = stream;
                void videoRef.current.play().catch(error => {
                    console.warn("Camera preview playback:", error);
                });
            }

            stream.getTracks().forEach((track) => {
                track.onended = () => {
                    if (!mountedRef.current) return;

                    stopRecording();
                    setCameraReady(false);
                    setError(
                        "Camera or microphone disconnected."
                    );
                    onReadyChange?.(false);
                };
            });

            setCameraReady(true);
            onReadyChange?.(true);
            setNotice("Camera and microphone ready.");

            // Start recording immediately once the live camera is attached.
            // Do not wait for a separate state-driven React effect.
            if (autoStart) {
                startRecording(stream);
            }
        } catch (caught) {
            console.error("Media permission error:", caught);
            setError(
                "Could not access camera and microphone. " +
                "Check browser permissions."
            );
        } finally {
            if (mountedRef.current) {
                setStarting(false);
            }
        }
    }


    function startRecording(liveStream: MediaStream) {
        if (
            !autoStart ||
            !liveStream.getVideoTracks().some(t => t.readyState === "live") ||
            !liveStream.getAudioTracks().some(t => t.readyState === "live") ||
            recording ||
            finalizing ||
            recordingStartedRef.current
        ) {
            setError("Recording could not start: check camera, microphone and exam permissions.");
            return;
        }


        if (!sessionId || !token || !clientId) {
            setError(
                "Missing exam authentication. Reopen the examination."
            );
            return;
        }

        setError("");
        resetRecording();

        try {
            const mimeType = selectMimeType();

            const options: MediaRecorderOptions = {
                videoBitsPerSecond: 400_000,
                audioBitsPerSecond: 40_000,
            };

            if (mimeType) {
                options.mimeType = mimeType;
            }

            const recorder = new MediaRecorder(
                liveStream,
                options
            );

            recorderRef.current = recorder;

            const actualMimeType =
                recorder.mimeType ||
                mimeType ||
                "video/webm";

            const uploadMimeType = actualMimeType
                .split(";", 1)[0]
                .toLowerCase();

            const fileExtension =
                uploadMimeType === "video/mp4" ? "mp4" : "webm";

            setExtension(fileExtension);

            recorder.ondataavailable = (event: BlobEvent) => {
                if (event.data.size === 0) return;

                const sequence = sequenceRef.current++;
                const blob = event.data;

                // Server uploads MUST continue for the full exam duration.
                // Only the optional in-memory backup is capped at 25 MB.
                if (mountedRef.current && !backupTruncatedRef.current) {
                    if (bytesRef.current + blob.size <= MAX_TEST_BYTES) {
                        chunksRef.current.push(blob);
                        bytesRef.current += blob.size;
                    } else {
                        backupTruncatedRef.current = true;
                        setNotice("Local backup limit reached; secure server uploads continue.");
                    }
                }
                if (mountedRef.current) setChunkCount(sequenceRef.current);
                // Final chunk must still upload even when React unmounts
                // this component following submission or timeout.
                queueChunk(blob, sequence, uploadMimeType);
            };

            recorder.onerror = () => {
                if (!mountedRef.current) return;

                setError("Browser recording error.");
                setRecording(false);
                setFinalizing(false);
            };

            recorder.onstop = () => {
                if (!mountedRef.current) return;

                const completeRecording = new Blob(
                    chunksRef.current,
                    { type: actualMimeType }
                );

                if (completeRecording.size > 0 && !backupTruncatedRef.current) {
                    const url = URL.createObjectURL(
                        completeRecording
                    );

                    downloadUrlRef.current = url;
                    setDownloadUrl(url);
                }

                setRecording(false);
                onRecordingChange?.(false);
                setNotice(
                    "Recording stopped. Checking final uploads..."
                );

                void uploadQueueRef.current.then(() => {
                    if (!mountedRef.current) return;

                    setFinalizing(false);

                    if (failedRef.current === 0) {
                        setNotice(
                            "All recording chunks were uploaded successfully."
                        );
                    } else {
                        setNotice(
                            `${failedRef.current} chunk(s) failed to upload. ` +
                            "Download the local recording as a backup."
                        );
                    }
                });
            };

            recorder.start(CHUNK_INTERVAL_MS);

            recordingStartedRef.current = true;
            setRecording(true);
            onRecordingChange?.(true);
            setNotice("Recording and uploading in progress.");
        } catch (caught) {
            console.error("Recording error:", caught);
            setError("Unable to start recording.");
        }
    }

    useEffect(() => {
        mountedRef.current = true;




        return () => {
            mountedRef.current = false;

            const recorder = recorderRef.current;

            if (recorder && recorder.state !== "inactive") {
                recorder.stop();
            }

            streamRef.current?.getTracks().forEach((track) => {
                track.onended = null;
                track.stop();
            });

            streamRef.current = null;

            if (downloadUrlRef.current) {
                URL.revokeObjectURL(downloadUrlRef.current);
            }
        };
    }, []);


    // Start the camera after React finishes mounting.

    useEffect(() => {
        if (!autoStart) return;

        const timer = window.setTimeout(() => {
            if (
                mountedRef.current &&
                !streamRef.current
            ) {
                void startCamera();
            }
        }, 0);

        return () => window.clearTimeout(timer);
    }, [autoStart]);


    // AI FACE DETECTION — Phase 2
    // 10s face absence / 5s multiple faces.
    // Observations do not terminate examinations.
    useEffect(() => {
        if (!cameraReady) return;

        let cancelled = false;
        let intervalId: number | undefined;

        let currentCondition = "";
        let conditionStartedAt = 0;
        let eventSent = false;
        let lastFaceBeepAt = 0;

        async function sendAIObservation(
            eventType: "ai_face_absent" | "ai_multiple_faces",
            durationSeconds: number,
            faceCount: number
        ) {
            try {
                const response = await fetch(
                    `${API}/api/exams/${encodeURIComponent(sessionId)}/proctoring/events`,
                    {
                        method: "POST",
                        headers: {
                            Authorization: `Bearer ${token}`,
                            "Content-Type": "application/json",
                        },
                        body: JSON.stringify({
                            event_type: eventType,
                            details: {
                                source: "mediapipe",
                                duration_seconds: durationSeconds,
                                face_count: faceCount,
                                message:
                                    eventType === "ai_face_absent"
                                        ? "Face not detected continuously"
                                        : "Multiple faces detected continuously",
                            },
                        }),
                    }
                );

                if (!response.ok) {
                    throw new Error(
                        `AI event upload failed: ${response.status}`
                    );
                }

                console.log("AI observation saved:", eventType);
            } catch (error) {
                console.error(
                    "Could not save AI observation:",
                    error
                );
            }
        }

        async function startAIDetection() {
            try {
                setAiFaceStatus("AI model loading...");

                await initializeFaceDetector();

                if (cancelled) return;

                setAiFaceStatus("AI face detection ready");

                intervalId = window.setInterval(() => {
                    const video = videoRef.current;

                    // Don't measure absence when the browser
                    // or camera preview isn't available.

                    if (
                        document.visibilityState !== "visible" ||
                        !video ||
                        video.readyState < 2 ||
                        video.paused ||
                        video.ended
                    ) {
                        setFaceWarningSeconds(null);
                        lastFaceBeepAt = 0;
                        currentCondition = "";
                        conditionStartedAt = 0;
                        eventSent = false;
                        return;
                    }


                    try {
                        const result = detectFaces(video);
                        const faceCount = result.faceCount;

                        const condition =
                            faceCount === 0
                                ? "absent"
                                : faceCount > 1
                                    ? "multiple"
                                    : "normal";

                        const now = performance.now();

                        if (condition !== currentCondition) {
                            currentCondition = condition;
                            conditionStartedAt = now;
                            eventSent = false;
                            lastFaceBeepAt = 0;

                            if (condition !== "absent") {
                                setFaceWarningSeconds(null);
                            }
                        }

                        const durationSeconds = Math.floor(
                            (now - conditionStartedAt) / 1000
                        );

                        if (condition === "normal") {
                            setAiFaceStatus(
                                "AI: One face detected"
                            );
                            return;
                        }

                        if (condition === "absent") {


                            if (durationSeconds >= 10) {
                                setFaceWarningSeconds(durationSeconds);
                            } else {
                                setFaceWarningSeconds(null);
                            }

                            // Beep once at 10 seconds.
                            if (durationSeconds >= 5 && lastFaceBeepAt === 0) {
                                playFaceWarningTone();
                                lastFaceBeepAt = 5;
                            }

                            // One reminder at 20 seconds, not every second.
                            if (durationSeconds >= 20 && lastFaceBeepAt === 5) {
                                playFaceWarningTone();
                                lastFaceBeepAt = 20;
                            }

                            setAiFaceStatus(
                                durationSeconds < 5
                                    ? "AI: No face detected"
                                    : `AI: No face (${durationSeconds}s)`
                            );

                            if (
                                durationSeconds >= 5 &&
                                !eventSent
                            ) {
                                eventSent = true;

                                setAiFaceStatus(
                                    "AI: Face absent — observation logged"
                                );

                                void sendAIObservation(
                                    "ai_face_absent",
                                    durationSeconds,
                                    0
                                );
                            }

                            return;
                        }

                        setAiFaceStatus(
                            `AI: ${faceCount} faces (${durationSeconds}s)`
                        );

                        if (
                            durationSeconds >= 5 &&
                            !eventSent
                        ) {
                            eventSent = true;

                            setAiFaceStatus(
                                "AI: Multiple faces — observation logged"
                            );

                            void sendAIObservation(
                                "ai_multiple_faces",
                                durationSeconds,
                                faceCount
                            );
                        }
                    } catch (error) {
                        console.error(
                            "AI detection error:",
                            error
                        );

                        currentCondition = "";
                        conditionStartedAt = 0;
                        eventSent = false;

                        setAiFaceStatus(
                            "AI detection unavailable"
                        );
                    }
                }, 1000);
            } catch (error) {
                console.error(
                    "AI initialization error:",
                    error
                );

                if (!cancelled) {
                    setAiFaceStatus(
                        "AI model failed to load"
                    );
                }
            }
        }

        void startAIDetection();

        return () => {
            cancelled = true;

            if (intervalId !== undefined) {
                window.clearInterval(intervalId);
            }
        };
    }, [cameraReady, sessionId, token]);




    // Keep the yellow face warning visible for at least 10 seconds.
    useEffect(() => {
        if (faceWarningSeconds !== null) {
            if (faceWarningShownAtRef.current === null) {
                faceWarningShownAtRef.current = Date.now();
            }

            setFaceWarningVisible(true);
            return;
        }

        if (faceWarningShownAtRef.current === null) {
            return;
        }

        const elapsed =
            Date.now() - faceWarningShownAtRef.current;

        const remaining = Math.max(0, 10_000 - elapsed);

        const timer = window.setTimeout(() => {
            setFaceWarningVisible(false);
            faceWarningShownAtRef.current = null;
        }, remaining);

        return () => window.clearTimeout(timer);
    }, [faceWarningSeconds]);


    // MOBILE PHONE DETECTION — Phase 3
    useEffect(() => {
        if (!cameraReady) return;

        let cancelled = false;
        let timer: number | undefined;
        let busy = false;

        let positiveChecks = 0;
        let negativeChecks = 0;
        let eventSent = false;

        async function startPhoneDetection() {
            try {
                setPhoneStatus("Loading phone detector...");

                await initializePhoneDetector();

                if (cancelled) return;

                setPhoneStatus("Phone detector ready");

                timer = window.setInterval(async () => {
                    const video = videoRef.current;

                    if (
                        cancelled ||
                        busy ||
                        document.visibilityState !== "visible" ||
                        !video ||
                        video.readyState < 2 ||
                        video.paused ||
                        video.ended
                    ) {
                        return;
                    }

                    busy = true;

                    try {
                        const phoneVisible =
                            await detectPhone(video);

                        if (cancelled) return;

                        if (phoneVisible) {
                            positiveChecks++;
                            negativeChecks = 0;

                            if (!eventSent) {
                                setPhoneStatus(
                                    "📱 Mobile phone detected — checking..."
                                );
                            }

                            if (
                                positiveChecks >= 2 &&
                                !eventSent
                            ) {
                                eventSent = true;

                                const response = await fetch(
                                    `${API}/api/exams/${encodeURIComponent(sessionId)}/proctoring/events`,
                                    {
                                        method: "POST",
                                        headers: {
                                            Authorization: `Bearer ${token}`,
                                            "Content-Type": "application/json",
                                        },
                                        body: JSON.stringify({
                                            event_type:
                                                "ai_mobile_phone",
                                            details: {
                                                source: "coco_ssd",
                                                confirmation_checks: 2,
                                                message:
                                                    "Mobile phone visible in webcam",
                                            },
                                        }),
                                    }
                                );


                                if (!response.ok) {
                                    throw new Error(
                                        `Phone event upload failed: ${response.status}`
                                    );
                                }

                                if (cancelled) return;

                                // Show popup only after successful backend saving.
                                phoneAlertUntilRef.current = Date.now() + 10_000;

                                setPhoneAlert(true);
                                playFaceWarningTone();

                                console.log(
                                    "AI observation saved: ai_mobile_phone"
                                );

                            }
                        } else {
                            negativeChecks++;
                            positiveChecks = 0;

                            if (negativeChecks >= 2) {
                                eventSent = false;
                            }

                            if (
                                negativeChecks >= 2 &&
                                Date.now() >= phoneAlertUntilRef.current
                            ) {
                                setPhoneAlert(false);
                            }
                        }
                    } catch (error) {
                        console.error(
                            "Phone detection error:",
                            error
                        );
                        if (!cancelled) {
                            setPhoneStatus(
                                "Phone detection unavailable"
                            );
                        }
                    } finally {
                        busy = false;
                    }
                }, 1000);
            } catch (error) {
                console.error(
                    "Phone model loading failed:",
                    error
                );

                if (!cancelled) {
                    setPhoneStatus(
                        "Phone detector failed to load"
                    );
                }
            }
        }

        void startPhoneDetection();

        return () => {
            cancelled = true;

            if (timer !== undefined) {
                window.clearInterval(timer);
            }
        };
    }, [cameraReady, sessionId, token]);


    useEffect(() => {
        if (!phoneAlert) return;

        const remaining = Math.max(
            0,
            phoneAlertUntilRef.current - Date.now()
        );

        const timeout = window.setTimeout(() => {
            setPhoneAlert(false);
        }, remaining);

        return () => {
            window.clearTimeout(timeout);
        };
    }, [phoneAlert]);


    return (
        <div className="student-recording-card">
            <h3>Live proctoring</h3>

            <video
                className="student-recording-video"
                ref={videoRef}
                autoPlay
                muted
                playsInline
            />

            <div className="student-recording-status">
                <span
                    className={
                        recording
                            ? "student-recording-dot is-active"
                            : "student-recording-dot"
                    }
                />

                <span>
                    {recording
                        ? "Recording active"
                        : finalizing
                            ? "Finishing secure upload..."
                            : cameraReady
                                ? "Camera connected"
                                : "Camera unavailable"}
                </span>
            </div>


            <div
                style={{
                    marginTop: 10,
                    padding: "10px 12px",
                    borderRadius: 8,
                    background: "#f3efff",
                    color: "#5131a5",
                    fontWeight: 600,
                    fontSize: 13,
                }}
            >
                🤖 {aiFaceStatus}
            </div>


            {phoneAlert && (
                <div
                    role="alert"
                    style={{
                        marginTop: 12,
                        padding: "14px 16px",
                        background: "#fff1f2",
                        border: "2px solid #e11d48",
                        color: "#9f1239",
                        borderRadius: 10,
                        fontWeight: 600,
                    }}
                >
                    <div style={{ fontSize: 16 }}>
                        ⚠️ Mobile Phone Detected
                    </div>

                    <p style={{ margin: "8px 0 0" }}>
                        A mobile phone has been detected
                        in your camera view.
                        This observation has been recorded
                        for teacher review.
                    </p>
                </div>
            )}


            {faceWarningVisible && (
                <div
                    role="alert"
                    style={{
                        marginTop: 12,
                        padding: "14px 16px",
                        background: "#fff3cd",
                        color: "#664d03",
                        border: "2px solid #ffca2c",
                        borderRadius: 10,
                        fontWeight: 600,
                    }}
                >
                    <div style={{ fontSize: 16 }}>
                        ⚠️ Face Not Detected
                    </div>

                    <p style={{ margin: "8px 0 0" }}>
                        {faceWarningSeconds !== null
                            ? `Your face has not been detected for ${faceWarningSeconds} seconds.`
                            : "Your face was temporarily outside the camera frame."}
                        Please sit properly in front of your
                        webcam and make sure your face is
                        clearly visible.
                    </p>
                </div>
            )}


            {failedCount > 0 && (
                <p role="alert" className="student-recording-error">
                    Recording upload issue detected.
                </p>
            )}

            {error && (
                <p role="alert" className="student-recording-error">
                    {error}
                </p>
            )}

            {downloadUrl && (failedCount > 0 || error) && (
                <a
                    href={downloadUrl}
                    download={`exampilot-${sessionId}.${extension}`}
                >
                    Download recording backup
                </a>
            )}
        </div>
    );
});

export default ExamCamera;
