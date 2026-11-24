import * as tf from "@tensorflow/tfjs";
import * as cocoSsd from "@tensorflow-models/coco-ssd";

let modelPromise: ReturnType<typeof cocoSsd.load> | null = null;

export async function initializePhoneDetector() {
    if (!modelPromise) {
        modelPromise = (async () => {
            await tf.ready();
            return cocoSsd.load({
                base: "lite_mobilenet_v2",
            });
        })().catch((error) => {
            modelPromise = null;
            throw error;
        });
    }

    return modelPromise;
}

export async function detectPhone(
    video: HTMLVideoElement
): Promise<boolean> {
    const model = await initializePhoneDetector();

    const predictions = await model.detect(video);

    return predictions.some(
        (prediction) =>
            prediction.class === "cell phone" &&
            prediction.score >= 0.55
    );
}


let phoneWarmUpPromise: Promise<void> | null = null;

export function warmUpPhoneDetector(): Promise<void> {
    if (!phoneWarmUpPromise) {
        phoneWarmUpPromise = (async () => {
            // Load the model using the existing cached loader.
            const model = await initializePhoneDetector();

            // Run the first prediction before the exam starts.
            const canvas = document.createElement("canvas");
            canvas.width = 320;
            canvas.height = 320;

            const context = canvas.getContext("2d");

            if (!context) {
                throw new Error("Canvas is unavailable");
            }

            context.fillStyle = "#000000";
            context.fillRect(0, 0, 320, 320);

            await model.detect(canvas);

            console.log("Phone detector loaded and warmed up");
        })().catch((error) => {
            phoneWarmUpPromise = null;
            throw error;
        });
    }

    return phoneWarmUpPromise;
}
