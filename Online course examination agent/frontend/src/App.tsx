import * as React from "react";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Activity,
  ArrowRight,
  BookOpen,
  Eye,
  EyeOff,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  FileText,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trophy,
  Users,
  Upload,
  Trash2,
  AlertTriangle,
} from "lucide-react";

import "./App.css";
import ExamCamera, { type ExamCameraHandle } from "./ExamCamera";
import { warmUpPhoneDetector } from "./PhoneDetector";

// ============================================================
// CONFIGURATION
// ============================================================

const API =
  (import.meta as any).env?.VITE_API_BASE_URL ||
  "http://127.0.0.1:8000";

// ============================================================
// TYPES
// ============================================================

type User = {
  email: string;
  name: string;
  role: "student" | "teacher";
  roll_number?: number | null;
  usn?: string | null;
  division?: string | null;
};

type Exam = {
  session_id: string;
  assignment_id?: string;
  status?: string;
  total_questions?: number;
  answered_questions?: number;
  questions?: any[];
  student_name?: string;
  student_roll_number?: number;
  scheduled_start_at?: string | null;
  scheduled_end_at?: string | null;
  duration_minutes?: number;
  started_at?: string | null;
  ends_at?: string | null;
};

type Note = {
  document_id: string;
  filename: string;
  file_type: string;
  file_size?: number;
  subject: string;
  topic?: string | null;
  processing_status: string;
  uploaded_at?: string;
};

// ============================================================
// API HELPER
// Supports JSON and multipart/form-data.
// ============================================================

async function req(
  path: string,
  token?: string,
  init: RequestInit = {}
) {
  const h: any = {
    ...(init.headers || {}),
  };

  if (!(init.body instanceof FormData)) {
    h["Content-Type"] = "application/json";
  }

  if (token) {
    h.Authorization = `Bearer ${token}`;
  }

  const r = await fetch(API + path, {
    ...init,
    headers: h,
  });

  const t = await r.text();

  let d: any = {};

  try {
    d = t ? JSON.parse(t) : {};
  } catch {
    d = { detail: t };
  }

  if (!r.ok) {
    const x = d.detail;

    throw Error(
      typeof x === "string"
        ? x
        : Array.isArray(x)
          ? x.map((v: any) => v.msg).join(", ")
          : x
            ? JSON.stringify(x)
            : `HTTP ${r.status}`
    );
  }

  return d;
}

const qid = (q: any, i: number) =>
  String(q.question_id || q.id || `q${i + 1}`);

// ============================================================
// MAIN APPLICATION
// ============================================================

export default function App() {

  // ==========================================================
  // AUTHENTICATION
  // ==========================================================

  const [token, setToken] = useState(
    localStorage.getItem("oce_token") || ""
  );

  const [user, setUser] = useState<User | null>(() => {
    try {
      return JSON.parse(
        localStorage.getItem("oce_user") || "null"
      );
    } catch {
      return null;
    }
  });

  const [mode, setMode] = useState<"login" | "register">("login");

  const [showPassword, setShowPassword] = useState(false);

  const [busy, setBusy] = useState(false);

  const [message, setMessage] = useState("");

  // ==========================================================
  // DASHBOARD
  // ==========================================================

  const [view, setView] = useState<
    "home" | "create" | "student-results" | "consent" | "prepare" | "exam" | "result"
  >("home");

  const [pendingExam, setPendingExam] = useState<Exam | null>(null);
  const [examConsent, setExamConsent] = useState(false);
  const [previewReady, setPreviewReady] = useState(false);
  const [phoneModelState, setPhoneModelState] =
    useState<"idle" | "loading" | "ready" | "error">("idle");
  const previewStreamRef = useRef<MediaStream | null>(null);
  const previewVideoRef = useRef<HTMLVideoElement>(null);

  function releasePreviewStream() {
    previewStreamRef.current?.getTracks().forEach(track => track.stop());
    previewStreamRef.current = null;
    setPreviewReady(false);
  }

  useEffect(() => {
    if (view !== "prepare" || !previewVideoRef.current || !previewStreamRef.current) return;
    const element = previewVideoRef.current;
    element.srcObject = previewStreamRef.current;
    void element.play().catch(error => console.warn("Preview playback:", error));
  }, [view, previewReady]);


  useEffect(() => {
    if (view !== "consent" && view !== "prepare") return;

    let cancelled = false;

    setPhoneModelState("loading");

    void warmUpPhoneDetector()
      .then(() => {
        if (!cancelled) {
          setPhoneModelState("ready");
        }
      })
      .catch((error) => {
        console.error(
          "Phone detector warm-up failed:",
          error
        );

        if (!cancelled) {
          setPhoneModelState("error");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [view]);

  const [recordingActive, setRecordingActive] = useState(false);
  const examCameraRef = useRef<ExamCameraHandle | null>(null);
  const [remainingSeconds, setRemainingSeconds] = useState<number | null>(null);
  const timeoutHandledRef = useRef(false);

  const [exams, setExams] = useState<Exam[]>([]);

  const [active, setActive] = useState<Exam | null>(null);

  // ========================================
  // PROCTORING STATE
  // ========================================

  const [examFullscreen, setExamFullscreen] = useState(false);

  const [securityViolations, setSecurityViolations] = useState(0);

  const [securityNotice, setSecurityNotice] = useState("");

  // Prevent events after the backend ends the examination.
  const examClosedRef = useRef(false);

  // Prevent rapidly repeated events of the same type.
  const lastSecurityEventsRef = useRef<Record<string, number>>({});

  // Keep track of answer requests still being saved.
  const pendingAnswerSavesRef = useRef<Promise<void>>(
    Promise.resolve()
  );

  // Pending debounce timers, one per question.
  const answerSaveTimersRef = useRef<
    Record<string, ReturnType<typeof setTimeout>>
  >({});

  // Latest unsent text for each question.
  const answerDraftsRef = useRef<Record<string, string>>({});

  // Prevent double submission.
  const submittingRef = useRef(false);

  // Identifies this browser's active examination client.
  const examClientRef = useRef<string>("");

  const [answers, setAnswers] = useState<
    Record<string, string>
  >({});

  const [result, setResult] = useState<any>(null);

  const [teacherResults, setTeacherResults] = useState<any[]>([]);
  const [selectedResultDivision, setSelectedResultDivision] = useState("");

  const [expandedWarningSession, setExpandedWarningSession] =
    useState<string | null>(null);


  const [recordingViewer, setRecordingViewer] = useState<{
    sessionId: string;
    url: string;
  } | null>(null);

  const [recordingLoading, setRecordingLoading] =
    useState<string | null>(null);


  const recordingVideoRef = useRef<HTMLVideoElement | null>(null);

  const pendingRecordingSeekRef = useRef<number | null>(null);

  function seekRecordingVideo(seconds: number) {
    const video = recordingVideoRef.current;

    if (!video || video.readyState < 1) {
      pendingRecordingSeekRef.current = seconds;
      return;
    }

    const target = Math.max(
      0,
      Number.isFinite(video.duration)
        ? Math.min(seconds, Math.max(0, video.duration - 0.1))
        : seconds
    );

    try {
      video.currentTime = target;
      pendingRecordingSeekRef.current = null;
    } catch (error) {
      console.warn("Could not seek recording yet:", error);
      pendingRecordingSeekRef.current = seconds;
    }
  }


  useEffect(() => {
    return () => {
      if (recordingViewer?.url) {
        URL.revokeObjectURL(recordingViewer.url);
      }
    };
  }, [recordingViewer?.url]);

  // ==========================================================
  // PROFESSOR NOTES
  // ==========================================================

  const [notes, setNotes] = useState<Note[]>([]);

  const [noteFile, setNoteFile] = useState<File | null>(null);

  const [noteSubject, setNoteSubject] = useState("DBMS");

  const [noteTopic, setNoteTopic] = useState("");

  const [uploadingNotes, setUploadingNotes] = useState(false);

  const [selectedDocuments, setSelectedDocuments] = useState<
    string[]
  >([]);


  // ==========================================================
  // PROCTORING MONITORING - SHARED EVENT HANDLER
  // ==========================================================

  const recordSecurityEvent = useCallback(
    async (eventType: string, warning: string) => {
      if (
        view !== "exam" ||
        !active?.session_id ||
        examClosedRef.current
      ) {
        return;
      }

      const sessionId = active.session_id;
      const now = Date.now();

      // Avoid repeated identical browser callbacks.
      const previous =
        lastSecurityEventsRef.current[eventType] || 0;

      if (now - previous < 1000) return;

      lastSecurityEventsRef.current[eventType] = now;
      setSecurityNotice(warning);

      try {
        const data = await req(
          `/api/exams/${encodeURIComponent(sessionId)}/proctoring/events`,
          token,
          {
            method: "POST",
            headers: {
              "X-Exam-Client": examClientRef.current,
            },
            body: JSON.stringify({
              event_type: eventType,
              details: { message: warning },
            }),
          }
        );

        if (examClosedRef.current) return;

        setSecurityViolations(data.incident_count);
        setSecurityNotice(data.warning_message);

        // The backend has ended the examination.
        if (data.exam_terminated) {
          examClosedRef.current = true;

          setSecurityNotice(
            "Exam terminated. Finishing recording upload..."
          );

          const recordingSaved =
            await examCameraRef.current?.finishRecording();

          setResult({
            ...(data.termination_result || {}),
            exam_terminated: true,
          });

          setExamFullscreen(false);
          setView("result");

          setMessage(
            recordingSaved === true
              ? "⛔ Exam terminated. Recording uploaded successfully."
              : "⛔ Exam terminated. Complete recording upload was not confirmed."
          );

          if (document.fullscreenElement) {
            try {
              await document.exitFullscreen();
            } catch (error) {
              console.warn(
                "Could not exit fullscreen:",
                error
              );
            }
          }
        }

      } catch (error: any) {
        if (examClosedRef.current) return;

        const errorText = String(
          error?.message || error
        );

        console.error(
          "Proctoring request failed:",
          error
        );

        // An earlier event may already have ended
        // the attempt. Confirm its current status.
        if (
          errorText.includes(
            "This examination has already ended"
          )
        ) {
          try {
            const exam = await req(
              `/api/exams/${encodeURIComponent(sessionId)}`,
              token
            );

            if (
              exam.status !== "in_progress" &&
              !examClosedRef.current
            ) {
              examClosedRef.current = true;

              let savedResult: any = {
                evaluation_pending: true,
              };

              try {
                savedResult = await req(
                  `/api/exams/${encodeURIComponent(sessionId)}/results`,
                  token
                );
              } catch (resultError) {
                console.warn(
                  "Results not yet available:",
                  resultError
                );
              }

              setResult({
                ...savedResult,
                exam_terminated: Boolean(
                  exam.proctoring_terminated
                ),
              });

              setExamFullscreen(false);
              setView("result");

              setMessage(
                "The examination has ended."
              );

              if (document.fullscreenElement) {
                await document.exitFullscreen()
                  .catch(console.warn);
              }

              return;
            }
          } catch (statusError) {
            console.error(
              "Could not check examination status:",
              statusError
            );
          }
        }

        if (!examClosedRef.current) {
          setSecurityNotice(
            `Security event could not be recorded: ${errorText}`
          );
        }
      }
    },
    [view, active?.session_id, token]
  );

  // Fullscreen and tab visibility monitoring.
  useEffect(() => {
    if (view !== "exam" || !active?.session_id) return;

    function handleFullscreenChange() {
      if (examClosedRef.current) return;

      const fullscreen =
        Boolean(document.fullscreenElement);

      if (!fullscreen && examFullscreen) {
        setExamFullscreen(false);

        void recordSecurityEvent(
          "fullscreen_exit",
          "Fullscreen exited! Please return to fullscreen."
        );
      }
    }

    function handleVisibilityChange() {
      if (examClosedRef.current) return;

      if (document.visibilityState === "hidden") {
        void recordSecurityEvent(
          "tab_switch",
          "Tab switching detected during examination!"
        );
      }
    }

    document.addEventListener(
      "fullscreenchange",
      handleFullscreenChange
    );

    document.addEventListener(
      "visibilitychange",
      handleVisibilityChange
    );

    return () => {
      document.removeEventListener(
        "fullscreenchange",
        handleFullscreenChange
      );

      document.removeEventListener(
        "visibilitychange",
        handleVisibilityChange
      );
    };
  }, [
    view,
    active?.session_id,
    examFullscreen,
    recordSecurityEvent,
  ]);

  // The actual server attempt begins only after the student clicks Start.
  async function enterExamFullscreen() {
    if (
      view !== "prepare" || !pendingExam || !examConsent ||
      !previewReady || busy ||
      !previewStreamRef.current?.getVideoTracks().some(t => t.readyState === "live") ||
      !previewStreamRef.current?.getAudioTracks().some(t => t.readyState === "live")
    ) {
      setMessage("⚠ Consent and a working camera/microphone are required.");
      return;
    }

    try {
      // This must be called directly from the click to satisfy browser rules.
      await document.documentElement.requestFullscreen();
      const started = await openExam(pendingExam);
      if (!started && document.fullscreenElement) {
        await document.exitFullscreen().catch(console.warn);
      }
    } catch (error: any) {
      setMessage(`⚠ Could not start in fullscreen: ${error?.message || error}`);
    }
  }

  // Copy, paste, right-click and focus monitoring.
  useEffect(() => {
    if (view !== "exam" || !active?.session_id) return;

    function handleCopy(event: ClipboardEvent) {
      if (
        examClosedRef.current ||
        !document.fullscreenElement
      ) return;

      event.preventDefault();

      void recordSecurityEvent(
        "copy_attempt",
        "Copying is not allowed during the examination."
      );
    }

    function handlePaste(event: ClipboardEvent) {
      if (
        examClosedRef.current ||
        !document.fullscreenElement
      ) return;

      event.preventDefault();

      void recordSecurityEvent(
        "paste_attempt",
        "Pasting is not allowed during the examination."
      );
    }

    function handleContextMenu(event: MouseEvent) {
      if (
        examClosedRef.current ||
        !document.fullscreenElement
      ) return;

      event.preventDefault();

      void recordSecurityEvent(
        "context_menu",
        "Right-click is disabled during the examination."
      );
    }

    function handleWindowBlur() {
      if (
        examClosedRef.current ||
        !document.fullscreenElement ||
        document.visibilityState !== "visible"
      ) return;

      void recordSecurityEvent(
        "window_blur",
        "Examination window lost focus."
      );
    }

    document.addEventListener("copy", handleCopy);
    document.addEventListener("paste", handlePaste);
    document.addEventListener(
      "contextmenu",
      handleContextMenu
    );
    window.addEventListener("blur", handleWindowBlur);

    return () => {
      document.removeEventListener("copy", handleCopy);
      document.removeEventListener("paste", handlePaste);
      document.removeEventListener(
        "contextmenu",
        handleContextMenu
      );
      window.removeEventListener(
        "blur",
        handleWindowBlur
      );
    };
  }, [
    view,
    active?.session_id,
    recordSecurityEvent,
  ]);




  // ==========================================================
  // EXAM COUNTDOWN AND AUTOMATIC TIMEOUT
  // ==========================================================

  useEffect(() => {
    if (
      view !== "exam" ||
      !active?.session_id ||
      !active.ends_at
    ) {
      return;
    }

    const sessionId = active.session_id;
    const deadline = new Date(active.ends_at).getTime();

    if (!Number.isFinite(deadline)) {
      setMessage("⚠ Invalid examination deadline.");
      return;
    }

    let cancelled = false;

    async function handleTimeout() {
      if (
        cancelled ||
        timeoutHandledRef.current ||
        examClosedRef.current ||
        submittingRef.current
      ) {
        return;
      }

      timeoutHandledRef.current = true;
      submittingRef.current = true;

      // Do not send late answers.
      for (const timer of Object.values(
        answerSaveTimersRef.current
      )) {
        clearTimeout(timer);
      }

      answerSaveTimersRef.current = {};
      answerDraftsRef.current = {};

      setRemainingSeconds(0);
      setMessage("⏰ Time is over. Finalizing your examination...");

      try {
        const recordingSaved =
          await examCameraRef.current?.finishRecording();

        if (cancelled) return;
        const data = await req(
          `/api/exams/${encodeURIComponent(sessionId)}/submit`,
          token,
          {
            method: "POST",
            headers: {
              "X-Exam-Client": examClientRef.current,
            },
            body: "{}",
          }
        );

        if (cancelled) return;

        examClosedRef.current = true;
        setResult(data);
        setMessage(
          recordingSaved === true
            ? "⏰ Time is over. Exam submitted and recording uploaded."
            : "⚠ Time is over. Exam submitted, but complete recording upload was not confirmed."
        );
        setExamFullscreen(false);
        setView("result");

        if (document.fullscreenElement) {
          await document.exitFullscreen().catch(console.warn);
        }

        void load().catch(console.error);
      } catch (error: any) {
        if (cancelled) return;

        // The submission may have already been finalized.
        try {
          const current = await req(
            `/api/exams/${encodeURIComponent(sessionId)}`,
            token
          );

          if (cancelled) return;

          if (current.status !== "in_progress") {
            examClosedRef.current = true;

            try {
              const saved = await req(
                `/api/exams/${encodeURIComponent(sessionId)}/results`,
                token
              );
              if (!cancelled) setResult(saved);
            } catch {
              if (!cancelled) {
                setResult({ evaluation_pending: true });
              }
            }

            if (!cancelled) {
              setMessage("⏰ Examination has ended.");
              setExamFullscreen(false);
              setView("result");
            }

            if (document.fullscreenElement) {
              await document.exitFullscreen().catch(console.warn);
            }
            return;
          }
        } catch (statusError) {
          console.error("Could not confirm exam status:", statusError);
        }

        if (!cancelled) {
          setMessage(
            `⚠ Time is over, but automatic submission could not be confirmed: ${error?.message || error
            }`
          );
          timeoutHandledRef.current = false;
        }
      } finally {
        submittingRef.current = false;
      }
    }

    function updateCountdown() {
      if (cancelled || examClosedRef.current) return;

      const seconds = Math.max(
        0,
        Math.ceil((deadline - Date.now()) / 1000)
      );

      setRemainingSeconds(seconds);

      if (seconds === 0) {
        void handleTimeout();
      }
    }

    updateCountdown();

    const interval = window.setInterval(updateCountdown, 1000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [view, active?.session_id, active?.ends_at, token]);


  // ==========================================================
  // EXAM SESSION HEARTBEAT
  // ==========================================================

  useEffect(() => {
    if (
      view !== "exam" ||
      !active?.session_id ||
      !examClientRef.current
    ) return;

    const sessionId = active.session_id;
    const clientId = examClientRef.current;

    let stopped = false;
    let running = false;

    async function heartbeat() {
      if (stopped || running || examClosedRef.current) {
        return;
      }

      running = true;

      try {
        await req(
          `/api/exams/${encodeURIComponent(sessionId)}/client/heartbeat`,
          token,
          {
            method: "POST",
            body: JSON.stringify({
              client_id: clientId,
            }),
          }
        );
      } catch (error: any) {
        if (stopped || examClosedRef.current) return;

        const reason = String(error?.message || error);

        if (
          reason.includes("already ended") ||
          reason.includes("another browser session") ||
          reason.includes("another session")
        ) {
          examClosedRef.current = true;

          setExamFullscreen(false);
          setView("home");
          setMessage(
            "Examination ended or opened in another session."
          );

          if (document.fullscreenElement) {
            void document.exitFullscreen().catch(console.warn);
          }

          return;
        }

        // Network failures are not cheating violations.
        setSecurityNotice(
          "Connection interrupted. Attempting to reconnect."
        );
      } finally {
        running = false;
      }
    }

    const interval = window.setInterval(
      () => void heartbeat(),
      15000
    );

    return () => {
      stopped = true;
      window.clearInterval(interval);
    };
  }, [view, active?.session_id, token]);


  // ==========================================================
  // AUTH FORM
  // ==========================================================

  const [a, setA] = useState({
    email: "",
    password: "",
    name: "",
    role: "student" as "student" | "teacher",
    roll: "101",
    usn: "TEST101",
    division: "A",
  });

  // ==========================================================
  // EXAM FORM
  // ==========================================================

  const [f, setF] = useState({
    division: "A",
    subject: "DBMS",
    topic: "SQL",
    difficulty: "L1",
    normal: 3,
    scenario: 1,
    coding: 1,
    count: 5,
  });

  // ==========================================================
  // EXAM SCHEDULING
  // ==========================================================

  const [durationMinutes, setDurationMinutes] = useState(30);
  const [scheduledDate, setScheduledDate] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");

  const teacher = user?.role === "teacher";

  const fail = (e: any) =>
    setMessage(`⚠ ${e.message || e}`);

  // ==========================================================
  // LOAD PROFESSOR NOTES
  // ==========================================================

  async function loadNotes() {
    if (!token || user?.role !== "teacher") return;

    const data = await req(
      "/api/teacher/notes",
      token
    );

    setNotes(
      Array.isArray(data.documents)
        ? data.documents
        : []
    );
  }

  // ==========================================================
  // LOAD DASHBOARD
  // ==========================================================

  async function load() {
    if (!token || !user) return;

    const d = await req(
      teacher
        ? "/api/teacher/exams"
        : "/api/student/exams",
      token
    );

    setExams(
      Array.isArray(d.exams)
        ? d.exams
        : []
    );

    if (teacher) {
      try {
        const r = await req(
          "/api/teacher/results",
          token
        );

        setTeacherResults(
          Array.isArray(r.results)
            ? r.results
            : []
        );
      } catch {
        setTeacherResults([]);
      }

      await loadNotes();
    }
  }


  async function watchRecording(
    sessionId: string,
    seekSeconds?: number
  ) {
    if (recordingLoading) return;


    if (
      recordingViewer?.sessionId === sessionId &&
      seekSeconds !== undefined
    ) {
      seekRecordingVideo(seekSeconds);
      return;
    }

    if (seekSeconds !== undefined) {
      pendingRecordingSeekRef.current = seekSeconds;
    } else {
      pendingRecordingSeekRef.current = null;
    }


    // Click again to close the current recording.
    if (recordingViewer?.sessionId === sessionId) {
      setRecordingViewer(null);
      return;
    }

    setRecordingLoading(sessionId);
    setMessage("");

    try {
      const response = await fetch(
        `${API}/api/teacher/exams/${encodeURIComponent(sessionId)}/recording-video`,
        {
          method: "GET",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (!response.ok) {
        const body = await response.text();

        if (response.status === 404) {
          throw new Error(
            "No recording has been uploaded for this attempt."
          );
        }

        throw new Error(
          `Could not load recording (${response.status}): ${body}`
        );
      }

      const blob = await response.blob();

      if (blob.size === 0) {
        throw new Error("Recording file is empty.");
      }

      const url = URL.createObjectURL(blob);

      setRecordingViewer({
        sessionId,
        url,
      });
    } catch (error: any) {
      setMessage(
        `⚠ ${error?.message || "Could not load recording"}`
      );
    } finally {
      setRecordingLoading(null);
    }
  }


  // ==========================================================
  // INITIALIZE AUTHENTICATED SESSION
  // ==========================================================

  useEffect(() => {
    if (!token) return;

    let cancelled = false;

    async function initialise() {

      let current: User;

      // Validate login.

      try {
        current = await req(
          "/api/auth/me",
          token
        );
      } catch (e: any) {

        if (cancelled) return;

        const error = String(e.message || e);

        if (
          error.includes("401") ||
          error.toLowerCase().includes(
            "invalid or expired login session"
          ) ||
          error.toLowerCase().includes(
            "invalid authentication credentials"
          )
        ) {
          localStorage.removeItem("oce_token");
          localStorage.removeItem("oce_user");

          setToken("");
          setUser(null);
          setExams([]);
          setNotes([]);

          setMessage(
            "Your login expired. Please sign in again."
          );
        } else {
          setMessage(
            `Could not verify login: ${error}`
          );
        }

        return;
      }

      if (cancelled) return;

      setUser(current);

      localStorage.setItem(
        "oce_user",
        JSON.stringify(current)
      );

      // Load appropriate dashboard.

      try {

        const path =
          current.role === "teacher"
            ? "/api/teacher/exams"
            : "/api/student/exams";

        const data = await req(path, token);

        if (!cancelled) {

          setExams(
            Array.isArray(data.exams)
              ? data.exams
              : []
          );

          setMessage("");

          if (current.role === "teacher") {

            try {
              const r = await req(
                "/api/teacher/results",
                token
              );

              if (!cancelled) {
                setTeacherResults(
                  Array.isArray(r.results)
                    ? r.results
                    : []
                );
              }
            } catch {
              if (!cancelled) {
                setTeacherResults([]);
              }
            }

            // Load professor notes.

            try {
              const notesData = await req(
                "/api/teacher/notes",
                token
              );

              if (!cancelled) {
                setNotes(
                  Array.isArray(notesData.documents)
                    ? notesData.documents
                    : []
                );
              }
            } catch (e: any) {
              if (!cancelled) {
                setMessage(
                  `Could not load professor notes: ${e.message || e
                  }`
                );
              }
            }
          }
        }

      } catch (e: any) {

        if (!cancelled) {

          setExams([]);

          setMessage(
            `Login succeeded, but exams could not be loaded: ${e.message || e
            }`
          );
        }
      }
    }

    initialise();

    return () => {
      cancelled = true;
    };

  }, [token]);

  // ==========================================================
  // AUTHENTICATION
  // ==========================================================

  async function auth(e: FormEvent) {

    e.preventDefault();

    setBusy(true);
    setMessage("");

    // Validate optional exam schedule.
    if (
      scheduledDate ||
      startTime ||
      endTime
    ) {
      if (!scheduledDate || !startTime || !endTime) {
        setMessage(
          "⚠ Please provide the date, start time and end time together."
        );
        return;
      }

      const start = new Date(`${scheduledDate}T${startTime}`);
      const end = new Date(`${scheduledDate}T${endTime}`);

      if (end <= start) {
        setMessage(
          "⚠ End time must be later than start time."
        );
        return;
      }

      if (start <= new Date()) {
        setMessage(
          "⚠ Scheduled start time must be in the future."
        );
        return;
      }
    }

    try {

      if (mode === "register") {

        await req(
          "/api/auth/register",
          undefined,
          {
            method: "POST",

            body: JSON.stringify({
              email: a.email,
              password: a.password,
              name: a.name,
              roll_number: Number(a.roll),
              usn: a.usn,
              division: a.division,
              role: a.role,
            }),
          }
        );

        setMode("login");

        setMessage(
          "Account created. Sign in now."
        );

      } else {

        const d = await req(
          "/api/auth/login",
          undefined,
          {
            method: "POST",

            body: JSON.stringify({
              email: a.email,
              password: a.password,
            }),
          }
        );

        setToken(d.access_token);

        setUser(d.user);

        localStorage.setItem(
          "oce_token",
          d.access_token
        );

        localStorage.setItem(
          "oce_user",
          JSON.stringify(d.user)
        );

        setMessage(
          `Signed in as ${d.user.role}.`
        );
      }

    } catch (e: any) {

      fail(e);

    } finally {

      setBusy(false);
    }
  }

  // ==========================================================
  // LOGOUT
  // ==========================================================

  function logout() {
    releasePreviewStream();

    setMessage("");
    setShowPassword(false);

    localStorage.removeItem("oce_token");
    localStorage.removeItem("oce_user");

    setToken("");
    setUser(null);

    setExams([]);
    setTeacherResults([]);
    setNotes([]);

    setSelectedDocuments([]);

    setView("home");
  }

  // ==========================================================
  // PROFESSOR NOTES UPLOAD
  // ==========================================================

  async function uploadNotes(e: FormEvent) {

    e.preventDefault();

    if (!noteFile) {
      setMessage("⚠ Please select a file.");
      return;
    }

    if (!noteSubject.trim()) {
      setMessage("⚠ Please enter the subject.");
      return;
    }

    setUploadingNotes(true);
    setMessage("");

    try {

      const formData = new FormData();

      formData.append("file", noteFile);
      formData.append("subject", noteSubject.trim());

      if (noteTopic.trim()) {
        formData.append("topic", noteTopic.trim());
      }

      const data = await req(
        "/api/teacher/notes",
        token,
        {
          method: "POST",
          body: formData,
        }
      );

      const uploaded =
        data.document || data;

      if (
        uploaded.processing_status === "processed"
      ) {
        setMessage(
          `✓ ${uploaded.filename || noteFile.name} uploaded and processed successfully.`
        );
      } else {
        setMessage(
          "⚠ File uploaded, but processing was not confirmed. Check the document status."
        );
      }

      setNoteFile(null);
      setNoteTopic("");

      const fileInput = document.getElementById(
        "professor-note-file"
      ) as HTMLInputElement | null;

      if (fileInput) {
        fileInput.value = "";
      }

      await loadNotes();

    } catch (e: any) {

      fail(e);

    } finally {

      setUploadingNotes(false);
    }
  }

  // ==========================================================
  // DELETE PROFESSOR NOTES
  // ==========================================================

  async function deleteNotes(documentId: string) {

    const confirmed = window.confirm(
      "Are you sure you want to delete this professor notes document?"
    );

    if (!confirmed) return;

    setBusy(true);

    try {

      await req(
        `/api/teacher/notes/${encodeURIComponent(documentId)}`,
        token,
        {
          method: "DELETE",
        }
      );

      setSelectedDocuments((previous) =>
        previous.filter((id) => id !== documentId)
      );

      await loadNotes();

      setMessage(
        "✓ Professor notes deleted successfully."
      );

    } catch (e: any) {

      fail(e);

    } finally {

      setBusy(false);
    }
  }

  // ==========================================================
  // SELECT PROFESSOR NOTES
  // ==========================================================

  function toggleDocument(documentId: string) {

    setSelectedDocuments((previous) =>
      previous.includes(documentId)
        ? previous.filter((id) => id !== documentId)
        : [...previous, documentId]
    );
  }

  // ==========================================================
  // CREATE EXAMINATION
  // ==========================================================

  async function create(e: FormEvent) {

    e.preventDefault();

    if (
      f.normal + f.scenario + f.coding !== f.count
    ) {
      setMessage(
        "⚠ Question mix must equal total questions."
      );

      return;
    }

    // Notes-only exam generation requires selected notes.

    if (selectedDocuments.length === 0) {
      setMessage(
        "⚠ Please select at least one professor notes document."
      );

      return;
    }

    const selectedNotes = notes.filter((note) =>
      selectedDocuments.includes(note.document_id)
    );

    if (
      selectedNotes.length !== selectedDocuments.length
    ) {
      setMessage(
        "⚠ One or more selected documents are unavailable. Refresh the notes list."
      );

      return;
    }

    if (
      selectedNotes.some(
        (note) => note.processing_status !== "processed"
      )
    ) {
      setMessage(
        "⚠ Select only successfully processed notes."
      );

      return;
    }

    if (
      selectedNotes.some(
        (note) =>
          note.subject.trim().toLowerCase() !==
          f.subject.trim().toLowerCase()
      )
    ) {
      setMessage(
        "⚠ Selected notes must belong to the selected subject."
      );

      return;
    }

    setBusy(true);
    setMessage("");

    try {

      /*
       * Preserve the existing division assignment approach.
       * The backend assigns the examination using the division.
       */
      const payload = {
        student: {
          name: `Division ${f.division}`,
          roll_number: 1,
          usn: `DIV-${f.division}`,
          division: f.division.trim(),
        },

        subject: f.subject,
        topic: f.topic,
        difficulty: f.difficulty,

        number_of_questions: Number(f.count),

        question_mix: {
          normal_mcq: Number(f.normal),
          scenario_mcq: Number(f.scenario),
          coding: Number(f.coding),
        },

        exam_mode: "practice",

        duration_minutes: durationMinutes,

        scheduled_start_at:
          scheduledDate && startTime
            ? new Date(
              `${scheduledDate}T${startTime}`
            ).toISOString()
            : null,

        scheduled_end_at:
          scheduledDate && endTime
            ? new Date(
              `${scheduledDate}T${endTime}`
            ).toISOString()
            : null,

        // Notes-only integration
        document_ids: selectedDocuments,
      };

      await req(
        "/api/exams",
        token,
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      );

      setMessage(
        `✓ Exam generated successfully for Division ${f.division}.`
      );

      setSelectedDocuments([]);

      setView("home");

      const refreshed = await req(
        "/api/teacher/exams",
        token
      );

      setExams(
        Array.isArray(refreshed.exams)
          ? refreshed.exams
          : []
      );

      await loadNotes();

    } catch (e: any) {

      fail(e);

    } finally {

      setBusy(false);
    }
  }

  // ==========================================================
  // OPEN STUDENT EXAM
  // ==========================================================

  async function openExam(x: Exam): Promise<boolean> {

    setBusy(true);
    setMessage("");

    try {

      if (!examConsent || !document.fullscreenElement) {
        throw new Error("Consent and fullscreen are required before starting.");
      }

      const d = await req(
        `/api/exams/${encodeURIComponent(x.assignment_id || x.session_id)}/start`,
        token,
        {
          method: "POST",
          body: JSON.stringify({ consent_accepted: true }),
        }
      );

      if (!d.session_id) {
        throw new Error(
          "Backend did not return a student exam session."
        );
      }

      if (d.status !== "in_progress") {
        setMessage(
          "This examination has already ended and cannot be reopened."
        );
        setView("prepare");
        return false;
      }


      // Register this browser with the backend.
      const clientKey = `exampilot_client_${d.session_id}`;

      let clientId = sessionStorage.getItem(clientKey);

      if (!clientId) {
        clientId = crypto.randomUUID();
        sessionStorage.setItem(clientKey, clientId);
      }

      await req(
        `/api/exams/${encodeURIComponent(d.session_id)}/client/claim`,
        token,
        {
          method: "POST",
          body: JSON.stringify({
            client_id: clientId,
          }),
        }
      );

      examClientRef.current = clientId;


      examClosedRef.current = false;
      lastSecurityEventsRef.current = {};
      pendingAnswerSavesRef.current = Promise.resolve();

      for (
        const timer of Object.values(
          answerSaveTimersRef.current
        )
      ) {
        clearTimeout(timer);
      }

      answerSaveTimersRef.current = {};
      answerDraftsRef.current = {};
      submittingRef.current = false;



      setExamFullscreen(Boolean(document.fullscreenElement));
      setSecurityViolations(0);
      setSecurityNotice("");

      timeoutHandledRef.current = false;
      setRecordingActive(false);

      const deadline = d.ends_at
        ? new Date(d.ends_at).getTime()
        : NaN;

      if (!Number.isFinite(deadline)) {
        throw new Error(
          "The backend did not provide a valid exam deadline."
        );
      }

      setRemainingSeconds(
        Math.max(0, Math.ceil((deadline - Date.now()) / 1000))
      );

      setActive(d);

      setAnswers({});

      setResult(null);

      setView("exam");
      return true;

    } catch (e: any) {
      fail(e);
      return false;
    } finally {
      setBusy(false);
    }
  }


  // ==========================================================
  // SAVE ANSWER DURING EXAMINATION
  // ==========================================================



  function saveAnswerImmediately(
    questionId: string,
    answer: string
  ): void {
    if (
      !active?.session_id ||
      examClosedRef.current ||
      submittingRef.current
    ) return;

    const sessionId = active.session_id;

    // Keep only the latest unsent answer.
    answerDraftsRef.current[questionId] = answer;

    // Cancel the previous timer for this question.
    const oldTimer =
      answerSaveTimersRef.current[questionId];

    if (oldTimer !== undefined) {
      clearTimeout(oldTimer);
    }

    answerSaveTimersRef.current[questionId] =
      setTimeout(() => {
        delete answerSaveTimersRef.current[questionId];

        const latest =
          answerDraftsRef.current[questionId];

        delete answerDraftsRef.current[questionId];

        if (
          latest === undefined ||
          examClosedRef.current ||
          submittingRef.current
        ) return;

        // Queue this save after previous saves.
        const save = pendingAnswerSavesRef.current
          .catch(() => undefined)
          .then(async () => {
            if (
              examClosedRef.current ||
              submittingRef.current
            ) return;

            await req(
              `/api/exams/${encodeURIComponent(sessionId)}/answers`,
              token,
              {
                method: "POST",
                headers: {
                  "X-Exam-Client": examClientRef.current,
                },
                body: JSON.stringify({
                  question_id: questionId,
                  answer: latest,
                }),
              }
            );
          });

        pendingAnswerSavesRef.current = save;

        void save.catch((error) => {
          if (examClosedRef.current) return;

          console.error(
            "Answer autosave failed:",
            error
          );

          setMessage(
            "⚠ An answer could not be autosaved. Please check your connection."
          );
        });
      }, 700);
  }



  // ==========================================================
  // SUBMIT STUDENT EXAM
  // ==========================================================



  async function submit() {
    if (
      !active ||
      busy ||
      examClosedRef.current ||
      submittingRef.current
    ) return;

    submittingRef.current = true;

    const sessionId = active.session_id;

    setBusy(true);
    setMessage("");

    try {
      // Stop all pending debounce timers.
      for (
        const timer of Object.values(
          answerSaveTimersRef.current
        )
      ) {
        clearTimeout(timer);
      }

      answerSaveTimersRef.current = {};
      answerDraftsRef.current = {};

      // Allow previously started requests to finish.
      // Final answers will be sent again below.
      await pendingAnswerSavesRef.current
        .catch((error) => {
          console.warn(
            "Earlier autosave failed:",
            error
          );
        });

      if (examClosedRef.current) return;

      // Save the latest displayed answer for every question.
      for (
        let i = 0;
        i < (active.questions || []).length;
        i++
      ) {
        if (examClosedRef.current) return;

        const id = qid(
          (active.questions || [])[i],
          i
        );

        if (answers[id] === undefined) continue;

        await req(
          `/api/exams/${encodeURIComponent(sessionId)}/answers`,
          token,
          {
            method: "POST",
            headers: {
              "X-Exam-Client": examClientRef.current,
            },
            body: JSON.stringify({
              question_id: id,
              answer: answers[id],
            }),
          }
        );
      }

      if (examClosedRef.current) return;

      setMessage("Finishing recording and uploading final video...");

      const recordingSaved =
        await examCameraRef.current?.finishRecording();

      // Use the existing manual submission endpoint.
      const data = await req(
        `/api/exams/${encodeURIComponent(sessionId)}/submit`,
        token,
        {
          method: "POST",
          headers: {
            "X-Exam-Client": examClientRef.current,
          },
          body: "{}",
        }
      );

      examClosedRef.current = true;

      setResult(data);
      setExamFullscreen(false);
      setView("result");

      setMessage(
        recordingSaved === true
          ? "✓ Examination submitted. Recording uploaded successfully."
          : "⚠ Examination submitted, but complete recording upload was not confirmed."
      );
      if (document.fullscreenElement) {
        await document.exitFullscreen().catch(
          (error) =>
            console.warn(
              "Fullscreen exit failed:",
              error
            )
        );
      }

      await load();

    } catch (error: any) {
      if (!examClosedRef.current) {
        fail(error);
      }

    } finally {
      submittingRef.current = false;
      setBusy(false);
    }
  }



  // ==========================================================
  // AUTHENTICATION SCREEN
  // ==========================================================

  if (!token || !user) {

    return (

      <div className="auth">

        <section className="hero">

          <div className="brand">
            <span className="logo">
              <BrainCircuit />
            </span>

            Exam<span>Pilot</span>
          </div>

          <div className="hero-copy">

            <small>
              ✦ AGENTIC EXAMINATION PLATFORM
            </small>

            <h1>
              Assess knowledge.
              <br />
              <em>Not just answers.</em>
            </h1>

            <p>
              Validated questions, secure exam sessions,
              and automated evaluation in one focused workspace.
            </p>

            <div className="features">

              <p>
                <ShieldCheck />

                <span>
                  <b>Secure by design</b>
                  <small>
                    Role-aware access and protected attempts
                  </small>
                </span>
              </p>

              <p>
                <BrainCircuit />

                <span>
                  <b>Agent-powered evaluation</b>
                  <small>
                    Structured scoring and feedback
                  </small>
                </span>
              </p>

              <p>
                <Activity />

                <span>
                  <b>Live exam workflow</b>
                  <small>
                    From creation to final result
                  </small>
                </span>
              </p>

            </div>

          </div>

          <small className="hero-foot">
            ONLINE COURSE EXAMINATION SYSTEM
          </small>

        </section>

        <section className="auth-main">

          <div className="auth-switch">

            {mode === "login"
              ? "New here?"
              : "Already registered?"}

            <button
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setShowPassword(false);
                setMessage("");
              }}
            >
              {mode === "login"
                ? "Create account"
                : "Sign in"}
            </button>

          </div>

          <div className="auth-card">

            <div className="auth-logo">
              <GraduationCap />
            </div>

            <small>
              {mode === "login"
                ? "YOUR WORKSPACE AWAITS"
                : "GET STARTED"}
            </small>

            <h2>
              {mode === "login"
                ? "Welcome back"
                : "Create your account"}
            </h2>

            <p>
              {mode === "login"
                ? "Sign in to continue to your workspace."
                : "Choose a role for your demo account."}
            </p>

            {message && (
              <div className="message">
                {message}
              </div>
            )}

            <form
              onSubmit={auth}
              className="stack"
            >

              {mode === "register" && (
                <>

                  <label>
                    Full name

                    <input
                      required
                      value={a.name}
                      onChange={(e) =>
                        setA({
                          ...a,
                          name: e.target.value,
                        })
                      }
                    />
                  </label>

                  <label>
                    Role

                    <select
                      value={a.role}
                      onChange={(e) =>
                        setA({
                          ...a,
                          role: e.target.value as any,
                        })
                      }
                    >
                      <option value="student">
                        Student
                      </option>

                      <option value="teacher">
                        Teacher
                      </option>
                    </select>
                  </label>

                  {a.role === "student" && (

                    <div className="two">

                      <label>
                        Roll number

                        <input
                          required
                          type="number"
                          value={a.roll}
                          onChange={(e) =>
                            setA({
                              ...a,
                              roll: e.target.value,
                            })
                          }
                        />
                      </label>

                      <label>
                        Division

                        <input
                          required
                          value={a.division}
                          onChange={(e) =>
                            setA({
                              ...a,
                              division: e.target.value,
                            })
                          }
                        />
                      </label>

                      <label className="wide">
                        USN

                        <input
                          required
                          value={a.usn}
                          onChange={(e) =>
                            setA({
                              ...a,
                              usn: e.target.value,
                            })
                          }
                        />
                      </label>

                    </div>
                  )}

                </>
              )}

              <label>
                Email

                <input
                  required
                  type="email"
                  value={a.email}
                  onChange={(e) =>
                    setA({
                      ...a,
                      email: e.target.value,
                    })
                  }
                />
              </label>


              <div className="auth-password-group">
                <label htmlFor="auth-password">Password</label>

                <div className="auth-password-field">
                  <input
                    id="auth-password"
                    required
                    type={showPassword ? "text" : "password"}
                    minLength={8}
                    value={a.password}
                    onChange={(e) =>
                      setA({
                        ...a,
                        password: e.target.value,
                      })
                    }
                  />

                  <button
                    type="button"
                    className="auth-password-toggle"
                    onClick={() => setShowPassword((previous) => !previous)}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    aria-pressed={showPassword}
                    title={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>


              <button
                className="primary full"
                disabled={busy}
              >
                {busy
                  ? "Please wait…"
                  : mode === "login"
                    ? "Sign in securely"
                    : "Create account"}

                <ArrowRight size={16} />
              </button>

            </form>

            <small className="footnote">
              <ShieldCheck size={14} />
              Credentials are handled by your backend.
            </small>

          </div>

          <small className="api-label">
            API service · {API}
          </small>

        </section>

      </div>
    );
  }

  // ==========================================================
  // MAIN DASHBOARD
  // ==========================================================

  return (

    <div className="layout">

      <aside className="sidebar">

        <div className="brand">
          <span className="logo">
            <BrainCircuit />
          </span>

          Exam<span>Pilot</span>
        </div>

        <small className="side-label">
          WORKSPACE
        </small>

        <button
          className={
            view === "home"
              ? "nav active"
              : "nav"
          }
          onClick={() => {
            if (view === "prepare") releasePreviewStream();
            setView("home");
          }}
        >
          <LayoutDashboard size={18} />
          Overview
        </button>


        {teacher && (
          <>
            <button
              className={
                view === "create"
                  ? "nav active"
                  : "nav"
              }
              onClick={() => setView("create")}
            >
              <Plus size={18} />
              Create exam
            </button>

            <button
              className={
                view === "student-results"
                  ? "nav active"
                  : "nav"
              }
              onClick={() => {
                setView("student-results");
                setMessage("");
              }}
            >
              <GraduationCap size={18} />
              Student results
            </button>
          </>

        )}


        <div className="side-bottom">

          <div className="online">
            ● API connected
          </div>

          <div className="profile">

            <div className="avatar">
              {user.name[0]}
            </div>

            <span>
              <b>{user.name}</b>

              <small>
                {user.role}
                {user.division
                  ? ` · Div ${user.division}`
                  : ""}
              </small>
            </span>

            <button
              className="icon"
              onClick={logout}
              title="Log out"
            >
              <LogOut size={16} />
            </button>

          </div>

        </div>

      </aside>

      <main className="main">

        <header className="topbar">

          <div>

            <small>
              WORKSPACE / {view.toUpperCase()}
            </small>

            <h1>
              {view === "prepare"
                ? "Camera check"
                : view === "consent"
                  ? "Examination consent"
                  : view === "create"
                    ? "Create an examination"
                    : view === "student-results"
                      ? "Student results"
                      : view === "exam"
                        ? "Exam in progress"
                        : view === "result"
                          ? "Evaluation results"
                          : `Good to see you, ${user.name.split(" ")[0]
                          }`}
            </h1>

          </div>

          <span className="role">
            {teacher
              ? <Users size={14} />
              : <GraduationCap size={14} />}

            {user.role}
          </span>

        </header>

        {message && (

          <div className="message">
            {message}

            <button
              onClick={() => setMessage("")}
            >
              ×
            </button>
          </div>

        )}

        {/* ================================================== */}
        {/* HOME DASHBOARD */}
        {/* ================================================== */}

        {view === "home" && (

          <>

            <section className="banner">

              <div>

                <small>
                  ✦ YOUR EXAMINATION HUB
                </small>

                <h2>
                  {teacher
                    ? "Design a better assessment."
                    : "Make every attempt count."}
                </h2>

                <p>
                  {teacher
                    ? "Create validated exams from professor notes and track their evaluation lifecycle."
                    : "Find assigned exams, submit answers, and review results."}
                </p>

                {teacher && (

                  <button
                    className="white-btn"
                    onClick={() => setView("create")}
                  >
                    Create new exam
                    <ArrowRight size={16} />
                  </button>

                )}

              </div>

              <div className="banner-icon">
                <BrainCircuit size={56} />
                <span>✓ Validated</span>
              </div>

            </section>

            <div className="section-head">

              <div>

                <h2>
                  {teacher
                    ? "Exam activity"
                    : "Your assigned exams"}
                </h2>

                <p>
                  {teacher
                    ? "Sessions created in this demo."
                    : "Exams assigned to your student identity."}
                </p>

              </div>

              <button
                className="secondary"
                onClick={() => load().catch(fail)}
              >
                <RefreshCw size={15} />
                Refresh
              </button>

            </div>

            <div className="stats">

              <div>
                <FileText />
                <small>
                  {teacher
                    ? "Exams created"
                    : "Assigned exams"}
                </small>
                <b>{exams.length}</b>
              </div>

              <div>
                <Clock3 />
                <small>In progress</small>

                <b>
                  {teacher
                    ? exams.filter(
                      (x: any) => Number(x.in_progress_count || 0) > 0
                    ).length
                    : exams.filter((x) => x.status === "in_progress").length}
                </b>
              </div>

              <div>
                <Trophy />
                <small>Completed</small>

                <b>
                  {teacher
                    ? exams.filter(
                      (x: any) => x.schedule_closed === true
                    ).length
                    : exams.filter((x) =>
                      /submitted|completed|evaluated|expired/i.test(
                        x.status || ""
                      )
                    ).length}
                </b>
              </div>

            </div>

            {!exams.length ? (

              <div className="empty">

                <BookOpen size={28} />

                <h3>
                  {teacher
                    ? "No exams created yet"
                    : "No exams assigned yet"}
                </h3>

                <p>
                  {teacher
                    ? "Upload professor notes and create your first examination."
                    : "Your teacher's exam will appear here once assigned."}
                </p>

                {teacher && (

                  <button
                    className="primary"
                    onClick={() => setView("create")}
                  >
                    Create first exam
                    <ArrowRight size={16} />
                  </button>

                )}

              </div>

            ) : (

              <div className="cards">

                {exams.map((x, i) => (

                  <article
                    className="exam-card"
                    key={x.session_id}
                  >

                    <div className="exam-top">
                      <BookOpen />

                      <span>
                        {(x.status || "ready").replaceAll(
                          "_",
                          " "
                        )}
                      </span>
                    </div>

                    <small>
                      SESSION {String(i + 1).padStart(2, "0")}
                    </small>

                    <h3>
                      {x.questions?.[0]?.subject ||
                        "Course assessment"}
                    </h3>

                    <p>
                      {teacher
                        ? `Assigned to Division ${(x as any).division ||
                        (x as any).target_division ||
                        "A"
                        }`
                        : "Complete this assessment and submit for evaluation."}
                    </p>

                    <div className="meta">

                      <span>
                        <Clock3 size={14} />
                        {x.answered_questions || 0} answered
                      </span>

                      <span>
                        {x.total_questions ||
                          x.questions?.length ||
                          0}{" "}
                        questions
                      </span>

                    </div>

                    {!teacher && (
                      <div className="exam-schedule-info">
                        {x.scheduled_start_at && (
                          <p>
                            <Clock3 size={14} />
                            Starts:{" "}
                            {new Date(
                              x.scheduled_start_at
                            ).toLocaleString("en-IN")}
                          </p>
                        )}

                        {x.scheduled_end_at && (
                          <p>
                            <Clock3 size={14} />
                            Ends:{" "}
                            {new Date(
                              x.scheduled_end_at
                            ).toLocaleString("en-IN")}
                          </p>
                        )}

                        {x.duration_minutes && (
                          <p>
                            Duration: {x.duration_minutes} minutes
                          </p>
                        )}
                      </div>
                    )}

                    {!teacher && (
                      <button
                        className="link-btn"
                        onClick={() => {
                          setPendingExam(x);
                          releasePreviewStream();
                          setExamConsent(false);
                          setRecordingActive(false);
                          setMessage("");
                          setView("consent");
                        }}
                        disabled={
                          busy ||
                          /submitted|completed|evaluated|locked|expired|timeout/i.test(
                            x.status || ""
                          )
                        }
                      >
                        {/expired|timeout/i.test(x.status || "")
                          ? "Exam expired"
                          : /submitted|completed|evaluated|locked/i.test(
                            x.status || ""
                          )
                            ? "Exam submitted"
                            : "Attend exam"}

                        {!/submitted|completed|evaluated|locked|expired|timeout/i.test(
                          x.status || ""
                        ) && <ArrowRight size={16} />}
                      </button>
                    )}

                  </article>

                ))}

              </div>

            )}

          </>

        )}

        {/* ================================================== */}
        {/* TEACHER RESULTS — ORIGINAL FRIEND 4 FUNCTIONALITY */}
        {/* ================================================== */}

        {view === "student-results" && teacher && (

          <section
            className="panel"
            style={{ marginTop: 28 }}
          >

            <div className="section-head">

              <div>
                <h2>Student results</h2>

                <p>
                  Results grouped division-wise and separately
                  for each exam.
                </p>
              </div>

              <button
                className="secondary"
                onClick={() => load().catch(fail)}
              >
                <RefreshCw size={15} />
                Refresh results
              </button>

            </div>

            {teacherResults.length === 0 ? (

              <div className="empty">
                <Trophy size={28} />

                <h3>No student submissions yet</h3>

                <p>
                  Results will appear here after a student
                  submits an assigned exam.
                </p>
              </div>

            ) : (

              (() => {

                const divisions = Array.from(
                  new Set(
                    teacherResults.map((r: any) =>
                      String(r.division || "Unassigned")
                    )
                  )
                ).sort();

                const activeDivision = divisions.includes(selectedResultDivision)
                  ? selectedResultDivision
                  : divisions[0];
                return (

                  <div className="teacher-results-layout">
                    <div className="teacher-division-tabs" role="tablist" aria-label="Choose division">
                      {divisions.map((division) => (
                        <button
                          key={division}
                          type="button"
                          role="tab"
                          aria-selected={activeDivision === division}
                          className={
                            activeDivision === division
                              ? "teacher-division-tab active"
                              : "teacher-division-tab"
                          }
                          onClick={() => {
                            setSelectedResultDivision(division);
                            setExpandedWarningSession(null);
                            setRecordingViewer(null);
                          }}
                        >
                          <Users size={16} />
                          {division === "Unassigned"
                            ? "Unassigned"
                            : `Division ${division}`}

                          <span>
                            {teacherResults.filter(
                              (r: any) =>
                                String(r.division || "Unassigned") === division
                            ).length}
                          </span>
                        </button>
                      ))}
                    </div>

                    {divisions
                      .filter((division: string) => division === activeDivision)
                      .map((division: string) => {

                        const divisionRows =
                          teacherResults.filter(
                            (r: any) =>
                              String(r.division || "Unassigned") ===
                              division
                          );

                        const examGroups = new Map<string, any[]>();

                        divisionRows.forEach((r: any) => {

                          const key = String(
                            r.assignment_id ||
                            `${r.subject || "Exam"}|${r.topic || ""}|${r.total_marks || ""}`
                          );

                          if (!examGroups.has(key)) {
                            examGroups.set(key, []);
                          }

                          examGroups.get(key)!.push(r);

                        });

                        return (

                          <section
                            key={division}
                            style={{
                              border: "1px solid #e8ebf4",
                              borderRadius: 18,
                              padding: 20,
                              background: "#fafbff",
                            }}
                          >

                            <div style={{ marginBottom: 18 }}>
                              <small>DIVISION</small>

                              <h2 style={{ margin: "4px 0 0" }}>
                                Division {division}
                              </h2>
                            </div>

                            <div style={{ display: "grid", gap: 20 }}>

                              {Array.from(
                                examGroups.entries()
                              ).map(([examKey, rows]) => {

                                const first = rows[0] || {};

                                const assignmentId =
                                  first.assignment_id;

                                const examIndex = assignmentId
                                  ? exams.findIndex(
                                    (x: any) =>
                                      x.session_id === assignmentId
                                  )
                                  : -1;

                                const sessionLabel =
                                  examIndex >= 0
                                    ? `Session ${String(
                                      examIndex + 1
                                    ).padStart(2, "0")}`
                                    : "Exam";

                                return (

                                  <details
                                    key={examKey}
                                    className="teacher-session-details"
                                  >

                                    <summary className="teacher-session-summary">

                                      <div>
                                        <small>{sessionLabel}</small>

                                        <h3 style={{ margin: "4px 0 0" }}>
                                          {first.subject || "Exam"}
                                          {first.topic
                                            ? ` · ${first.topic}`
                                            : ""}
                                        </h3>
                                      </div>

                                      <span className="pill">
                                        {rows.length} submission
                                        {rows.length === 1 ? "" : "s"}
                                      </span>

                                    </summary>

                                    <div style={{ overflowX: "auto" }}>

                                      <table
                                        style={{
                                          width: "100%",
                                          borderCollapse: "collapse",
                                          minWidth: 650,
                                        }}
                                      >

                                        <thead>
                                          <tr>
                                            <th style={{ textAlign: "left", padding: 12 }}>Student</th>
                                            <th style={{ textAlign: "left", padding: 12 }}>USN</th>
                                            <th style={{ textAlign: "left", padding: 12 }}>Marks</th>
                                            <th style={{ textAlign: "left", padding: 12 }}>Percentage</th>
                                            <th style={{ textAlign: "left", padding: 12 }}>Status</th>
                                            <th style={{ textAlign: "left", padding: 12 }}>
                                              Browser Warnings
                                            </th>

                                            <th style={{ textAlign: "left", padding: 12 }}>
                                              AI Observations
                                            </th>
                                            <th style={{ textAlign: "left", padding: 12 }}>
                                              Recording
                                            </th>
                                          </tr>
                                        </thead>

                                        <tbody>


                                          {rows.map((r: any, i: number) => {
                                            const sessionId = String(
                                              r.session_id || i
                                            );

                                            const isBrowserExpanded =
                                              expandedWarningSession === `${sessionId}:browser`;

                                            const isAiExpanded =
                                              expandedWarningSession === `${sessionId}:ai`;

                                            const isExpanded = isBrowserExpanded || isAiExpanded;

                                            const warningCount =
                                              Number(r.warning_count || 0);


                                            const events = Array.isArray(r.proctoring_events)
                                              ? r.proctoring_events
                                              : [];


                                            const aiEvents = events.filter(
                                              (event: any) =>
                                                String(event.event_type || "").startsWith("ai_")
                                            );


                                            const examStartMs = r.started_at
                                              ? new Date(r.started_at).getTime()
                                              : NaN;

                                            const getVideoSeconds = (event: any): number | null => {
                                              const eventMs = new Date(event.occurred_at || "").getTime();

                                              if (
                                                !Number.isFinite(examStartMs) ||
                                                !Number.isFinite(eventMs)
                                              ) {
                                                return null;
                                              }

                                              // Face events are logged after a detection threshold.
                                              // Rewind to approximately when the observation began.
                                              const rewindSeconds =
                                                event.event_type === "ai_face_absent" ? 5 :
                                                  event.event_type === "ai_multiple_faces" ? 5 :
                                                    0;

                                              return Math.max(
                                                0,
                                                (eventMs - examStartMs) / 1000 - rewindSeconds
                                              );
                                            };

                                            const formatVideoTime = (seconds: number): string => {
                                              const whole = Math.floor(seconds);
                                              const minutes = Math.floor(whole / 60);
                                              const remaining = whole % 60;

                                              return `${String(minutes).padStart(2, "0")}:${String(
                                                remaining
                                              ).padStart(2, "0")}`;
                                            };


                                            const browserEvents = events.filter(
                                              (event: any) =>
                                                !String(event.event_type || "").startsWith("ai_")
                                            );

                                            const aiEventLabels: Record<string, string> = {
                                              ai_face_absent: "Face Absent",
                                              ai_multiple_faces: "Multiple Faces Detected",
                                              ai_mobile_phone: "Mobile Phone Detected",
                                            };

                                            const getEventLabel = (event: any) =>
                                              aiEventLabels[event.event_type] ||
                                              String(event.event_type || "Unknown Event")
                                                .replaceAll("_", " ");


                                            return (
                                              <React.Fragment key={sessionId}>
                                                <tr
                                                  style={{
                                                    borderTop: "1px solid #e8ebf4",
                                                  }}
                                                >
                                                  <td style={{ padding: 12 }}>
                                                    {r.student_name || r.name || "Student"}
                                                  </td>

                                                  <td style={{ padding: 12 }}>
                                                    {r.student_usn || r.usn || "—"}
                                                  </td>

                                                  <td style={{ padding: 12 }}>
                                                    <b>
                                                      {r.marks ?? r.marks_awarded ?? 0}
                                                      {" / "}
                                                      {r.total_marks ?? 0}
                                                    </b>
                                                  </td>

                                                  <td style={{ padding: 12 }}>
                                                    <b>{r.percentage ?? 0}%</b>
                                                  </td>

                                                  <td style={{ padding: 12 }}>
                                                    {r.proctoring_terminated
                                                      ? "Terminated (security)"
                                                      : r.status || "Completed"}
                                                  </td>

                                                  <td style={{ padding: 12 }}>
                                                    <button
                                                      type="button"
                                                      className="secondary"
                                                      aria-expanded={isBrowserExpanded}
                                                      aria-label={`View browser warnings for ${r.student_name || "student"}`}
                                                      onClick={() =>
                                                        setExpandedWarningSession(
                                                          isBrowserExpanded
                                                            ? null
                                                            : `${sessionId}:browser`
                                                        )
                                                      }
                                                      style={{
                                                        display: "inline-flex",
                                                        alignItems: "center",
                                                        gap: 8,
                                                      }}
                                                    >
                                                      <AlertTriangle
                                                        size={16}
                                                        color={
                                                          warningCount > 0
                                                            ? "#c2410c"
                                                            : "#16a34a"
                                                        }
                                                      />
                                                      {warningCount}
                                                    </button>
                                                  </td>


                                                  <td style={{ padding: 12 }}>
                                                    <button
                                                      type="button"
                                                      className="secondary"
                                                      aria-expanded={isAiExpanded}
                                                      aria-label={`View AI observations for ${r.student_name || "student"}`}
                                                      onClick={() =>
                                                        setExpandedWarningSession(
                                                          isAiExpanded
                                                            ? null
                                                            : `${sessionId}:ai`
                                                        )
                                                      }
                                                      style={{
                                                        display: "inline-flex",
                                                        alignItems: "center",
                                                        gap: 8,
                                                        whiteSpace: "nowrap",
                                                      }}
                                                    >
                                                      <BrainCircuit
                                                        size={16}
                                                        color={
                                                          aiEvents.length > 0
                                                            ? "#7c3aed"
                                                            : "#64748b"
                                                        }
                                                      />

                                                      {aiEvents.length}
                                                    </button>
                                                  </td>


                                                  <td style={{ padding: 12 }}>
                                                    <button
                                                      type="button"
                                                      className="secondary"
                                                      disabled={
                                                        recordingLoading !== null
                                                      }
                                                      onClick={() =>
                                                        void watchRecording(sessionId)
                                                      }
                                                    >
                                                      {recordingLoading === sessionId
                                                        ? "Loading..."
                                                        : recordingViewer?.sessionId === sessionId
                                                          ? "Close Recording"
                                                          : "▶ Watch Recording"}
                                                    </button>
                                                  </td>
                                                </tr>


                                                {recordingViewer?.sessionId === sessionId && (
                                                  <tr>
                                                    <td
                                                      colSpan={8}
                                                      style={{
                                                        padding: 18,
                                                        background: "#f8fafc",
                                                      }}
                                                    >
                                                      <h4>
                                                        Student Examination Recording
                                                      </h4>

                                                      <video
                                                        key={recordingViewer.url}
                                                        src={recordingViewer.url}
                                                        controls
                                                        playsInline
                                                        preload="metadata"


                                                        ref={recordingVideoRef}
                                                        onLoadedMetadata={() => {
                                                          const seconds = pendingRecordingSeekRef.current;

                                                          if (seconds !== null) {
                                                            seekRecordingVideo(seconds);
                                                          }
                                                        }}

                                                        style={{
                                                          display: "block",
                                                          width: "100%",
                                                          maxWidth: 720,
                                                          borderRadius: 12,
                                                          background: "#111",
                                                        }}
                                                      />


                                                    </td>
                                                  </tr>
                                                )}



                                                {isExpanded && (
                                                  <tr>
                                                    <td
                                                      colSpan={7}
                                                      style={{
                                                        padding: 16,
                                                        background: "#fafbff",
                                                      }}
                                                    >


                                                      <div className="proctor-card">

                                                        {/* AI OBSERVATIONS — ONLY WHEN AI IS OPEN */}
                                                        {isAiExpanded && (
                                                          <>
                                                            <div className="proctor-card-header">
                                                              <h4>🤖 AI Observations</h4>
                                                              <p>
                                                                {aiEvents.length} AI observation(s)
                                                                recorded during this examination.
                                                                All detections require teacher review.
                                                              </p>
                                                            </div>

                                                            {aiEvents.length === 0 ? (
                                                              <p>No AI observations recorded.</p>
                                                            ) : (
                                                              <div className="proctor-event-list">
                                                                {aiEvents.map((event: any, index: number) => (
                                                                  <div
                                                                    key={event.id ?? index}
                                                                    className="proctor-event-item"
                                                                    style={{
                                                                      borderLeft: "4px solid #7c3aed",
                                                                      paddingLeft: 12,
                                                                      marginBottom: 12,
                                                                    }}
                                                                  >
                                                                    <div className="proctor-event-top">
                                                                      <strong>
                                                                        {getEventLabel(event)}
                                                                      </strong>

                                                                      <span className="proctor-event-time">
                                                                        {event.occurred_at
                                                                          ? new Date(
                                                                            event.occurred_at
                                                                          ).toLocaleString()
                                                                          : "Time unavailable"}
                                                                      </span>
                                                                    </div>

                                                                    <p style={{ margin: "6px 0" }}>
                                                                      {event.message ||
                                                                        "AI observation recorded"}
                                                                    </p>


                                                                    {(() => {
                                                                      const videoSeconds = getVideoSeconds(event);

                                                                      if (videoSeconds === null) {
                                                                        return (
                                                                          <small style={{ color: "#64748b" }}>
                                                                            Recording position unavailable
                                                                          </small>
                                                                        );
                                                                      }

                                                                      return (
                                                                        <button
                                                                          type="button"
                                                                          className="secondary"
                                                                          disabled={recordingLoading !== null}
                                                                          onClick={() =>
                                                                            void watchRecording(sessionId, videoSeconds)
                                                                          }
                                                                          style={{
                                                                            marginTop: 8,
                                                                            display: "inline-flex",
                                                                            alignItems: "center",
                                                                            gap: 6,
                                                                            fontSize: 13,
                                                                          }}
                                                                        >
                                                                          ▶ Watch near {formatVideoTime(videoSeconds)}
                                                                        </button>
                                                                      );
                                                                    })()}


                                                                    {typeof event.details?.duration_seconds ===
                                                                      "number" && (
                                                                        <div>
                                                                          <small>
                                                                            Duration:{" "}
                                                                            {event.details.duration_seconds}s
                                                                          </small>
                                                                        </div>
                                                                      )}

                                                                    {typeof event.details?.face_count ===
                                                                      "number" && (
                                                                        <div>
                                                                          <small>
                                                                            Faces detected:{" "}
                                                                            {event.details.face_count}
                                                                          </small>
                                                                        </div>
                                                                      )}
                                                                  </div>
                                                                ))}
                                                              </div>
                                                            )}
                                                          </>
                                                        )}

                                                        {/* BROWSER WARNINGS — ONLY WHEN BROWSER IS OPEN */}
                                                        {isBrowserExpanded && (
                                                          <>
                                                            <div className="proctor-card-header">
                                                              <h4>🛡️ Browser Security Warnings</h4>
                                                              <p>
                                                                {warningCount} counted browser warning(s)
                                                                during this examination.
                                                              </p>
                                                            </div>

                                                            {r.proctoring_terminated && (
                                                              <div className="proctor-alert">
                                                                Examination terminated after the
                                                                browser-security incident limit
                                                                was reached.
                                                              </div>
                                                            )}

                                                            {browserEvents.length === 0 ? (
                                                              <p>No browser-security events recorded.</p>
                                                            ) : (
                                                              <div className="proctor-event-list">
                                                                {browserEvents.map(
                                                                  (event: any, index: number) => (
                                                                    <div
                                                                      key={event.id ?? index}
                                                                      className="proctor-event-item"
                                                                      style={{
                                                                        borderLeft:
                                                                          "4px solid #f59e0b",
                                                                        paddingLeft: 12,
                                                                        marginBottom: 12,
                                                                      }}
                                                                    >
                                                                      <div className="proctor-event-top">
                                                                        <strong>
                                                                          {getEventLabel(event)}
                                                                        </strong>

                                                                        <span className="proctor-event-time">
                                                                          {event.occurred_at
                                                                            ? new Date(
                                                                              event.occurred_at
                                                                            ).toLocaleString()
                                                                            : "Time unavailable"}
                                                                        </span>
                                                                      </div>

                                                                      <p style={{ margin: "6px 0" }}>
                                                                        {event.message ||
                                                                          "Browser event recorded"}
                                                                      </p>
                                                                    </div>
                                                                  )
                                                                )}
                                                              </div>
                                                            )}
                                                          </>
                                                        )}

                                                      </div>


                                                    </td>
                                                  </tr>
                                                )}
                                              </React.Fragment>
                                            );
                                          })}


                                        </tbody>

                                      </table>

                                    </div>

                                  </details>

                                );

                              })}

                            </div>

                          </section>

                        );

                      })}

                  </div>

                );

              })()

            )}

          </section>

        )}

        {/* ================================================== */}
        {/* CREATE EXAM — TEACHER */}
        {/* ================================================== */}

        {view === "create" && !teacher && (

          <section className="panel">

            <h2>Access restricted</h2>

            <p>
              Only teacher accounts can create exams.
            </p>

            <button
              className="primary"
              onClick={() => setView("home")}
            >
              Back to student dashboard
            </button>

          </section>

        )}

        {view === "create" && teacher && (

          <>

            {/* ---------------------------------------------- */}
            {/* PROFESSOR NOTES MANAGEMENT */}
            {/* ---------------------------------------------- */}

            <section className="panel teacher-notes-panel">

              <div className="section-head">

                <div>
                  <h2>Professor notes</h2>

                  <p>
                    Upload lecture materials to generate
                    examination questions from your notes.
                  </p>
                </div>

                <span className="pill">
                  {notes.length} documents
                </span>

              </div>

              {/* UPLOAD FORM */}

              <form
                onSubmit={uploadNotes}
                className="exam-form"
              >

                <h3>
                  <Upload size={18} />
                  Upload new notes
                </h3>

                <div className="grid three">

                  <label>
                    Subject

                    <select
                      value={noteSubject}
                      onChange={(e) =>
                        setNoteSubject(e.target.value)
                      }
                    >
                      <option value="DBMS">DBMS</option>
                      <option value="OOP">OOP</option>
                      <option value="OS">OS</option>
                      <option value="CN">CN</option>
                    </select>
                  </label>

                  <label>
                    Topic

                    <input
                      value={noteTopic}
                      placeholder="e.g. Classes and Objects"
                      onChange={(e) =>
                        setNoteTopic(e.target.value)
                      }
                    />
                  </label>

                  <label>
                    Select file

                    <input
                      id="professor-note-file"
                      type="file"
                      accept=".pdf,.docx,.pptx,.txt"
                      required
                      onChange={(e) =>
                        setNoteFile(
                          e.target.files?.[0] || null
                        )
                      }
                    />

                    <small>
                      PDF, DOCX, PPTX, TXT · Max 25 MB
                    </small>
                  </label>

                </div>

                {noteFile && (

                  <div className="message">
                    Selected: {noteFile.name}
                  </div>

                )}

                <div className="form-end">

                  <span>
                    <b>Notes processing</b>

                    <small>
                      Text extraction, chunking and embeddings
                      are handled by the backend.
                    </small>
                  </span>

                  <button
                    className="primary"
                    disabled={uploadingNotes || !noteFile}
                  >
                    {uploadingNotes
                      ? "Uploading..."
                      : "Upload professor notes"}

                    <Upload size={16} />
                  </button>

                </div>

              </form>

              {/* UPLOADED NOTES */}

              <div className="section-head" style={{ marginTop: 30 }}>

                <div>
                  <h2>Uploaded documents</h2>

                  <p>
                    Your available professor notes.
                  </p>
                </div>

                <button
                  className="secondary"
                  onClick={() => loadNotes().catch(fail)}
                >
                  <RefreshCw size={15} />
                  Refresh
                </button>

              </div>

              {notes.length === 0 ? (

                <div className="empty">
                  <FileText size={28} />

                  <h3>No professor notes uploaded</h3>

                  <p>
                    Upload lecture notes to begin generating
                    notes-based examinations.
                  </p>
                </div>

              ) : (

                <div className="cards">

                  {notes.map((note) => (

                    <article
                      className="exam-card"
                      key={note.document_id}
                    >

                      <div className="exam-top">
                        <FileText />

                        <span>
                          {note.processing_status}
                        </span>
                      </div>

                      <h3>{note.filename}</h3>

                      <p>
                        {note.subject}
                        {note.topic
                          ? ` · ${note.topic}`
                          : ""}
                      </p>

                      <div className="meta">

                        <span>
                          {note.file_type?.toUpperCase() || "FILE"}
                        </span>

                        <span>
                          {note.file_size
                            ? `${(note.file_size / (1024 * 1024)).toFixed(2)} MB`
                            : ""}
                        </span>

                      </div>

                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() =>
                          deleteNotes(note.document_id)
                        }
                      >
                        <Trash2 size={15} />
                        Delete
                      </button>

                    </article>

                  ))}

                </div>

              )}

            </section>

            {/* ---------------------------------------------- */}
            {/* EXAM CONFIGURATION */}
            {/* ---------------------------------------------- */}

            <section className="panel teacher-configuration-panel">

              <h2>Exam configuration</h2>

              <p>
                Configure your examination using the uploaded
                professor notes.
              </p>

              <div className="teacher-form-guide">
                <div>
                  <span className="teacher-guide-number">01</span>
                  <strong>Exam details</strong>
                  <small>Division, subject and difficulty</small>
                </div>

                <div>
                  <span className="teacher-guide-number">02</span>
                  <strong>Question setup</strong>
                  <small>Notes and question mix</small>
                </div>

                <div>
                  <span className="teacher-guide-number">03</span>
                  <strong>Schedule & generate</strong>
                  <small>Review before creating</small>
                </div>
              </div>

              <form
                onSubmit={create}
                className="exam-form"
              >

                <h3>01 · Target division</h3>

                <div className="grid three">

                  <label>
                    Division

                    <input
                      required
                      value={f.division}
                      onChange={(e) =>
                        setF({
                          ...f,
                          division: e.target.value,
                        })
                      }
                    />
                  </label>

                </div>

                <h3>02 · Assessment details</h3>

                <div className="grid three">

                  <label>
                    Subject

                    <select
                      value={f.subject}
                      onChange={(e) => {
                        setF({
                          ...f,
                          subject: e.target.value,
                        });

                        setSelectedDocuments([]);
                      }}
                    >
                      <option value="DBMS">DBMS</option>
                      <option value="OOP">OOP</option>
                      <option value="OS">OS</option>
                      <option value="CN">CN</option>
                      <option value="OOPS">OOPS</option>
                    </select>
                  </label>

                  <label>
                    Topic

                    <input
                      required
                      value={f.topic}
                      onChange={(e) =>
                        setF({
                          ...f,
                          topic: e.target.value,
                        })
                      }
                    />
                  </label>

                  <label>
                    Difficulty

                    <select
                      value={f.difficulty}
                      onChange={(e) =>
                        setF({
                          ...f,
                          difficulty: e.target.value,
                        })
                      }
                    >
                      <option value="L1">L1 - Easy</option>
                      <option value="L2">L2 - Medium</option>
                      <option value="L3">L3 - Hard</option>
                    </select>
                  </label>

                </div>

                <h3>03 · Select professor notes</h3>

                <p>
                  Select the documents that should be used
                  for question generation.
                </p>

                {notes.filter(
                  (note) =>
                    note.processing_status === "processed" &&
                    note.subject.trim().toLowerCase() ===
                    f.subject.trim().toLowerCase()
                ).length === 0 ? (

                  <div className="empty">

                    <FileText size={28} />

                    <h3>No matching processed notes</h3>

                    <p>
                      Upload processed notes for{" "}
                      <b>{f.subject}</b> first.
                    </p>

                  </div>

                ) : (

                  <div className="cards">

                    {notes
                      .filter(
                        (note) =>
                          note.processing_status === "processed" &&
                          note.subject.trim().toLowerCase() ===
                          f.subject.trim().toLowerCase()
                      )
                      .map((note) => (

                        <label
                          key={note.document_id}
                          className={
                            selectedDocuments.includes(note.document_id)
                              ? "exam-card teacher-note-choice selected"
                              : "exam-card teacher-note-choice"
                          }
                        >

                          <div
                            style={{
                              display: "flex",
                              alignItems: "flex-start",
                              gap: 12,
                            }}
                          >

                            <input
                              type="checkbox"
                              checked={selectedDocuments.includes(
                                note.document_id
                              )}
                              onChange={() =>
                                toggleDocument(note.document_id)
                              }
                            />

                            <div>

                              <b>{note.filename}</b>

                              <p>
                                {note.subject}
                                {note.topic
                                  ? ` · ${note.topic}`
                                  : ""}
                              </p>

                              <small>
                                {note.file_type?.toUpperCase()} · Processed
                              </small>

                            </div>

                          </div>

                        </label>

                      ))}

                  </div>

                )}

                <h3>04 · Question mix</h3>

                <div className="mix">
                  {[
                    ["Normal MCQ", "normal"],
                    ["Scenario MCQ", "scenario"],
                    ["Coding / SQL", "coding"],
                    ["Total questions", "count"],
                  ].map(([label, key]) => (
                    <label key={key}>
                      {label}
                      <input
                        type="number"
                        min={key === "count" ? 1 : 0}
                        value={(f as any)[key]}
                        onChange={(e) =>
                          setF({
                            ...f,
                            [key]: Number(e.target.value),
                          })
                        }
                      />
                    </label>
                  ))}
                </div>

                <h3>05 · Exam schedule</h3>

                <div className="teacher-schedule-help">
                  <Clock3 size={20} />

                  <div>
                    <strong>Set when students can take this examination</strong>
                    <p>
                      Exam duration is the time each student receives
                      after starting. The scheduled date and start/end
                      times control when the exam is available.
                    </p>
                  </div>
                </div>

                <div className="grid three">
                  <label>
                    Exam duration
                    <select
                      value={durationMinutes}
                      onChange={(e) =>
                        setDurationMinutes(Number(e.target.value))
                      }
                    >
                      <option value={30}>30 minutes</option>
                      <option value={45}>45 minutes</option>
                      <option value={60}>60 minutes</option>
                      <option value={90}>90 minutes</option>
                      <option value={120}>120 minutes</option>
                    </select>
                  </label>

                  <label>
                    Scheduled date
                    <input
                      type="date"
                      value={scheduledDate}
                      onChange={(e) =>
                        setScheduledDate(e.target.value)
                      }
                    />
                  </label>

                  <label>
                    Start time
                    <input
                      type="time"
                      value={startTime}
                      onChange={(e) =>
                        setStartTime(e.target.value)
                      }
                    />
                  </label>

                  <label>
                    End time
                    <input
                      type="time"
                      value={endTime}
                      onChange={(e) =>
                        setEndTime(e.target.value)
                      }
                    />
                  </label>
                </div>



                <p>
                  Leave the schedule fields empty to make the exam
                  available immediately.
                </p>



                <div className="teacher-exam-review">
                  <div className="teacher-review-heading">
                    <div>
                      <h3>Review your examination</h3>
                      <p>
                        Confirm these settings before generating questions.
                      </p>
                    </div>
                    <CheckCircle2 size={22} />
                  </div>

                  <div className="teacher-review-grid">
                    <div>
                      <small>Target division</small>
                      <strong>Division {f.division || "Not selected"}</strong>
                    </div>

                    <div>
                      <small>Subject & topic</small>
                      <strong>{f.subject} · {f.topic || "No topic"}</strong>
                    </div>

                    <div>
                      <small>Difficulty</small>
                      <strong>
                        {f.difficulty === "L1"
                          ? "Easy"
                          : f.difficulty === "L2"
                            ? "Medium"
                            : "Hard"}
                      </strong>
                    </div>

                    <div>
                      <small>Question distribution</small>
                      <strong>
                        {f.normal} MCQ · {f.scenario} Scenario · {f.coding} Coding
                      </strong>
                    </div>

                    <div>
                      <small>Selected documents</small>
                      <strong>{selectedDocuments.length} selected</strong>
                    </div>

                    <div>
                      <small>Exam duration</small>
                      <strong>{durationMinutes} minutes</strong>
                    </div>

                    <div className="teacher-review-wide">
                      <small>Availability</small>
                      <strong>
                        {scheduledDate && startTime && endTime
                          ? `${scheduledDate} · ${startTime} – ${endTime}`
                          : scheduledDate || startTime || endTime
                            ? "Schedule incomplete"
                            : "Available immediately"}
                      </strong>
                    </div>
                  </div>
                </div>

                <div className="form-end">

                  <span>

                    <b>
                      {f.normal + f.scenario + f.coding} of {f.count} questions configured
                    </b>

                    <div
                      className={
                        f.normal + f.scenario + f.coding === f.count
                          ? "teacher-form-validation valid"
                          : "teacher-form-validation invalid"
                      }
                    >
                      {f.normal + f.scenario + f.coding === f.count
                        ? "✓ Question distribution is valid"
                        : "⚠ The question types must add up to the total"}
                    </div>

                    <small>
                      Selected documents: {selectedDocuments.length}
                      <br />
                      Question mix must equal total.
                    </small>

                  </span>

                  <button
                    className="primary"
                    disabled={
                      busy ||
                      selectedDocuments.length === 0 ||
                      f.normal + f.scenario + f.coding !== f.count
                    }
                  >
                    {busy
                      ? "Generating..."
                      : "Generate exam"}

                    <Sparkles size={16} />

                  </button>

                </div>

              </form>

            </section>

          </>

        )}


        {view === "consent" && pendingExam && (
          <section className="panel student-consent">
            <h2>Examination Consent</h2>
            <p className="student-intro">
              Before starting, please review the examination
              monitoring requirements.
            </p>

            <div className="student-stepper">
              <span className="step-current">1 · Consent</span>
              <span>2 · Camera check</span>
              <span>3 · Examination</span>
            </div>

            <div className="student-info-box">
              <div className="student-info-heading">
                <ShieldCheck size={20} />
                <strong>Secure examination monitoring</strong>
              </div>

              <p>
                Your webcam and microphone will be recorded only
                after you start the examination.
              </p>
              <p>
                The recording is uploaded to ExamPilot and is
                accessible to the authorized examiner.
              </p>
            </div>

            <label className="student-consent-choice"
            >
              <input
                type="checkbox"
                checked={examConsent}
                onChange={(e) =>
                  setExamConsent(e.target.checked)
                }
              />

              <span>
                I consent to webcam and microphone recording
                throughout this examination.
              </span>
            </label>

            <div className="student-actions">
              <button
                className="primary"
                type="button"
                disabled={!examConsent || busy}
                onClick={async () => {
                  if (!examConsent || !pendingExam || busy) return;
                  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
                    setMessage("⚠ This browser cannot record camera and microphone.");
                    return;
                  }
                  setBusy(true);
                  setMessage("");
                  try {
                    releasePreviewStream();
                    const stream = await navigator.mediaDevices.getUserMedia({
                      video: { width: { ideal: 640 }, height: { ideal: 360 }, frameRate: { ideal: 15 } },
                      audio: { echoCancellation: true, noiseSuppression: true },
                    });
                    if (
                      !stream.getVideoTracks().some(track => track.readyState === "live") ||
                      !stream.getAudioTracks().some(track => track.readyState === "live")
                    ) {
                      stream.getTracks().forEach(track => track.stop());
                      throw new Error("Both camera and microphone must be working.");
                    }
                    previewStreamRef.current = stream;
                    setPreviewReady(true);
                    setView("prepare");
                  } catch (error: any) {
                    setMessage(`⚠ Camera/microphone permission required: ${error?.message || error}`);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy
                  ? "Checking camera and microphone..."
                  : "Agree & Preview Camera"}
              </button>

              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => {
                  setPendingExam(null);
                  setExamConsent(false);
                  setView("home");
                }}
              >
                Cancel
              </button>
            </div>

            <p className="student-consent-note">
              <small>
                Without consent and camera/microphone access,
                you cannot begin the examination.
              </small>
            </p>
          </section>
        )}


        {view === "prepare" && pendingExam && (
          <section className="panel student-prepare">
            <h2>Camera Check — Ready to Begin</h2>
            <div className="student-stepper">
              <span>1 · Consent</span>
              <span className="step-current">2 · Camera check</span>
              <span>3 · Examination</span>
            </div>
            <p>Preview your face and check your camera position. <b>The exam timer has not started, and nothing is being recorded.</b></p>

            <div className="student-preview-area">
              <video
                className="student-preview-video"
                ref={previewVideoRef}
                autoPlay
                muted
                playsInline
              />

              <div
                className={
                  previewReady
                    ? "student-camera-status"
                    : "student-camera-status is-unavailable"
                }
              >
                {previewReady
                  ? "✓ Camera and microphone connected — preview only"
                  : "Camera or microphone unavailable"}
              </div>
            </div>

            <p>When you click Start, ExamPilot will enter fullscreen, create your timed attempt, and begin webcam/microphone recording automatically.</p>

            <p role="status" style={{ marginTop: 12 }}>
              {phoneModelState === "loading"
                ? "⏳ Preparing AI mobile-phone detector..."
                : phoneModelState === "ready"
                  ? "✅ AI mobile-phone detector ready"
                  : phoneModelState === "error"
                    ? "⚠ Mobile-phone detector unavailable."
                    : ""}
            </p>

            <div className="student-actions">
              <button
                type="button" className="primary"

                disabled={
                  !examConsent ||
                  !previewReady ||
                  busy ||
                  phoneModelState === "loading"
                }

                onClick={() => void enterExamFullscreen()}
              >
                {busy ? "Starting examination..." : "Enter Fullscreen and Start Exam"}
              </button>
              <button
                type="button" className="secondary" disabled={busy}
                onClick={() => {
                  releasePreviewStream();
                  setExamConsent(false);
                  setPendingExam(null);
                  setView("home");
                }}
              >Cancel</button>
            </div>
          </section>
        )}

        {/* ================================================== */}
        {/* STUDENT EXAMINATION — PRESERVED */}
        {/* ================================================== */}

        {view === "exam" && active && (

          <section className="panel student-exam-panel">


            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: 16,
                marginBottom: 18,
                background:
                  remainingSeconds !== null && remainingSeconds <= 60
                    ? "#fef2f2"
                    : "#f1f5f9",
                borderRadius: 12,
              }}
            >
              <div>
                <h3 style={{ margin: 0 }}>Examination Timer</h3>
                <small>Time remaining for this attempt</small>
              </div>


              <div
                className={`student-exam-timer ${remainingSeconds !== null && remainingSeconds <= 60
                  ? "timer-warning"
                  : ""
                  }`}
              >
                <div>
                  <h3>Examination Timer</h3>
                  <p>Time remaining for this attempt</p>
                </div>

                <div
                  className="student-exam-time"
                  role="timer"
                  aria-label="Exam time remaining"
                >
                  {remainingSeconds === null
                    ? "--:--"
                    : `${String(Math.floor(remainingSeconds / 60)).padStart(2, "0")}:${String(remainingSeconds % 60).padStart(2, "0")}`}
                </div>
              </div>

            </div>


            <div className="student-exam-workspace">
              <div className="student-exam-camera-column">

                <ExamCamera
                  ref={examCameraRef}
                  sessionId={active.session_id}
                  token={token}
                  clientId={examClientRef.current}
                  autoStart={true}
                  initialStream={previewStreamRef.current}
                  onRecordingChange={setRecordingActive}
                />

              </div>

              <div className="student-exam-questions-column">




                {!recordingActive ? (
                  <div style={{ padding: 20 }}>
                    <h3>Starting secure recording...</h3>
                    <p>Please remain in fullscreen. Exam questions unlock as soon as recording starts.</p>
                    {securityNotice && <p role="alert" style={{ color: "red" }}>⚠ {securityNotice}</p>}
                  </div>
                ) : !examFullscreen ? (
                  <div style={{ padding: 20 }}>
                    <h3>Fullscreen exited</h3>
                    <p>Return to fullscreen to continue. The security incident is logged, and recording continues.</p>
                    <button type="button" className="primary" onClick={() => {
                      void document.documentElement.requestFullscreen()
                        .then(() => setExamFullscreen(true))
                        .catch(() => setSecurityNotice("Fullscreen permission denied."));
                    }}>Return to Fullscreen</button>
                  </div>
                ) : (
                  <>
                    <div className="student-security-summary">
                      <span>
                        <ShieldCheck size={17} />
                        Secure Exam Mode
                      </span>

                      <strong>
                        Security incidents: {securityViolations} / 4
                      </strong>
                    </div>

                    {securityNotice && (
                      <div className="student-security-alert" role="alert">
                        <AlertTriangle size={18} />
                        <span>{securityNotice}</span>
                      </div>
                    )}

                    <div className="student-questions-header">
                      <div>
                        <h2>Assessment questions</h2>
                        <p>Choose your answers carefully before submitting.</p>
                      </div>

                      <span className="student-question-count">
                        {(active.questions || []).length} questions
                      </span>
                    </div>

                    {(active.questions || []).map((q, i) => {

                      const id = qid(q, i);

                      const opts = Array.isArray(q.options)
                        ? q.options.map((v: any, j: number) => [
                          String.fromCharCode(65 + j),
                          String(v),
                        ])
                        : Object.entries(q.options || {});

                      return (

                        <article
                          className="question"
                          key={id}
                        >

                          <small>
                            QUESTION {i + 1} · {q.question_type || "MCQ"}
                          </small>

                          <h3>
                            {q.question ||
                              q.text ||
                              "Question text unavailable."}
                          </h3>

                          {opts.length ? (

                            <div className="options">

                              {opts.map(([k, v]: any) => (

                                <label
                                  key={k}
                                  className={
                                    answers[id] === k
                                      ? "chosen"
                                      : ""
                                  }
                                >

                                  <input
                                    type="radio"
                                    name={id}
                                    checked={answers[id] === k}
                                    onChange={() => {
                                      setAnswers((previous) => ({
                                        ...previous,
                                        [id]: k,
                                      }));

                                      void saveAnswerImmediately(id, k);
                                    }}
                                  />

                                  <b>{k}</b>

                                  {v}

                                </label>

                              ))}

                            </div>

                          ) : (

                            <label>
                              Your answer

                              <textarea
                                rows={4}
                                value={answers[id] || ""}
                                onChange={(e) => {
                                  const value = e.target.value;

                                  setAnswers((previous) => ({
                                    ...previous,
                                    [id]: value,
                                  }));

                                  void saveAnswerImmediately(id, value);
                                }}
                              />

                            </label>

                          )}

                        </article>

                      );

                    })}

                    <button
                      className="primary"
                      disabled={busy}
                      onClick={submit}
                    >
                      {busy
                        ? "Submitting…"
                        : "Submit for evaluation"}

                      <ArrowRight size={16} />

                    </button>

                  </>
                )}
              </div>
            </div>

          </section>

        )}

        {/* ================================================== */}
        {/* EVALUATION RESULTS — PRESERVED */}
        {/* ================================================== */}

        {view === "result" &&
          result &&
          (() => {

            const payload =
              result?.result ||
              result?.evaluation_results ||
              result;

            const rows = Array.isArray(payload?.results)
              ? payload.results
              : Array.isArray(payload)
                ? payload
                : [];

            const obtained = rows.reduce(
              (s: number, r: any) =>
                s + Number(r.marks_awarded || 0),
              0
            );

            const total = rows.reduce(
              (s: number, r: any) =>
                s + Number(r.total_marks || 0),
              0
            );

            const percentage =
              total > 0
                ? Math.round((obtained / total) * 100)
                : 0;

            return (

              <section className="panel">

                <div className="empty">

                  <Trophy size={34} />

                  <h2>
                    {result.exam_terminated
                      ? "Examination Terminated"
                      : "Thank you!"}
                  </h2>

                  <p>
                    {result.exam_terminated
                      ? "Your examination was automatically ended because the security violation limit was reached."
                      : result.evaluation_pending
                        ? "Your examination has been submitted. Evaluation is pending."
                        : "Your examination has been submitted for evaluation."}
                  </p>

                  {total > 0 && (

                    <div
                      className="stats"
                      style={{
                        width: "100%",
                        marginTop: 20,
                      }}
                    >

                      <div>
                        <Trophy />
                        <small>Marks</small>
                        <b>
                          {obtained} / {total}
                        </b>
                      </div>

                      <div>
                        <CheckCircle2 />
                        <small>Percentage</small>
                        <b>{percentage}%</b>
                      </div>

                      <div>
                        <ShieldCheck />
                        <small>Status</small>
                        <b>
                          {result.exam_terminated
                            ? "Terminated"
                            : result.evaluation_pending
                              ? "Pending"
                              : "Completed"}
                        </b>
                      </div>

                    </div>

                  )}

                  <button
                    className="primary"
                    onClick={() => {
                      setView("home");
                      setActive(null);
                      setResult(null);
                      setAnswers({});
                      load().catch(fail);
                    }}
                  >
                    Back to overview
                  </button>

                </div>

              </section>

            );

          })()}

        {/* ================================================== */}
        {/* FOOTER */}
        {/* ================================================== */}

        <footer>
          ExamPilot · Online Course Examination System

          <span>
            Connected to {API}
          </span>
        </footer>

      </main>

    </div>

  );
}