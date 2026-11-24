
import {
  FaceDetector,
  FilesetResolver,
} from "@mediapipe/tasks-vision";

export type FaceDetectionResult = {
  faceCount: number;
  status: "no_face" | "one_face" | "multiple_faces";
};

let detector: FaceDetector | null = null;

export async function initializeFaceDetector(): Promise<void> {
  if (detector) return;

  const vision = await FilesetResolver.forVisionTasks(
    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision/wasm"
  );

  detector = await FaceDetector.createFromOptions(vision, {
    baseOptions: {
      modelAssetPath:
        "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
      delegate: "CPU",
    },
    runningMode: "VIDEO",
    minDetectionConfidence: 0.5,
  });
}

export function detectFaces(
  video: HTMLVideoElement
): FaceDetectionResult {
  if (!detector) {
    throw new Error("Face detector is not initialized");
  }

  if (video.readyState < 2) {
    throw new Error("Video is not ready");
  }

  const result = detector.detectForVideo(
    video,
    performance.now()
  );

  const faceCount = result.detections.length;

  return {
    faceCount,
    status:
      faceCount === 0
        ? "no_face"
        : faceCount === 1
        ? "one_face"
        : "multiple_faces",
  };
}

export function closeFaceDetector(): void {
  detector?.close();
  detector = null;
}