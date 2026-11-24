# ExamPilot 🎓

### An Agent-Powered Online Examination and AI-Assisted Proctoring Platform

**ExamPilot** is a full-stack examination management platform that helps educators create assessments grounded in uploaded course materials, schedule and assign exams, evaluate student submissions, and review examination activity. Its agentic question-generation workflow uses **LangGraph** and retrieval from selected teacher notes; its proctoring module combines browser-security monitoring, webcam/microphone recording, and AI-assisted observations for teacher review.

> **Project scope:** ExamPilot is an academic/development project. AI detection events are observations that require human review, **not evidence of cheating by themselves**. The platform is not presented as production-certified secure examination software.

## Contents

- [What ExamPilot does](#what-exampilot-does)
- [Core features](#core-features)
- [Agentic examination workflow](#agentic-examination-workflow)
- [End-to-end workflow](#end-to-end-workflow)
- [AI-assisted proctoring](#ai-assisted-proctoring)
- [Technology stack](#technology-stack)
- [Project layout](#project-layout)
- [Local setup](#local-setup)
- [How to test](#how-to-test)
- [Limitations and responsible use](#limitations-and-responsible-use)

## What ExamPilot does

ExamPilot brings together five connected functions:

1. **Teacher material management:** upload lecture notes and choose documents for an assessment.
2. **Agentic exam generation:** retrieve relevant passages, generate questions and validate the generated items against source materials.
3. **Exam delivery:** assign examinations to students by division, apply optional schedules and duration limits, collect answers and finalize attempts.
4. **Evaluation and reporting:** save student submissions and assessment results in PostgreSQL and display them in a teacher results view.
5. **AI-assisted proctoring:** record webcam/microphone evidence and distinguish browser-security incidents from AI observations.

## Core features

### 👩‍🏫 Teacher workspace

- Teacher authentication and role-aware access.
- Upload, view, select and delete course notes in supported formats: **PDF, DOCX, PPTX and TXT**.
- Create exams using **selected course materials**, subject, topic, difficulty, number of questions and question-type distribution.
- Supported generation categories include **normal MCQs, scenario-based MCQs and coding questions**.
- Set exam duration and optional scheduled start/end times.
- Assign and review exams by student division.
- View marks, percentages, status, browser warnings, AI observations and available exam recordings.

### 🧑‍🎓 Student workspace

- Student login, division-based exam listing and assigned assessment access.
- Exam start checks, schedule restrictions and countdown timer.
- Answer submission and persisted evaluation results.
- Informed webcam/microphone consent before entering the proctored exam.
- Fullscreen assessment view with monitoring of selected browser activities.

### 📊 Evaluation and persistence

- Examination assignments, attempts, student answers and evaluation results persist through **PostgreSQL**.
- The backend integrates the exam lifecycle with evaluation and the teacher's results page.
- A separate timeout-worker entry point exists for handling expired examinations. **The worker was manually verified in an earlier integration; continuous background scheduling/deployment must be configured separately.**

## Agentic examination workflow

The exam-generation system is more than a proctoring app: it includes an AI workflow for producing assessments from teacher-provided study material.

```text
Teacher uploads lecture notes
            │
            ▼
Document text extraction (PDF / DOCX / PPTX / TXT)
            │
            ▼
Text chunking + embeddings / vector retrieval
            │
            ▼
Select relevant source passages
            │
            ▼
LangGraph exam-generation workflow
            │
            ├── Question Generation Agent
            │     Produces the requested question types
            │     from retrieved lecture-note content
            │
            └── Validation Agent
                  Checks question structure, requested
                  count/mix and source-grounding metadata
            │
            ▼
Teacher-created exam / assignment
            │
            ▼
Student attempts → evaluation → saved results
```

### Agent roles

| Agent / component | Responsibility |
| --- | --- |
| **Question Generation Agent** | Generates questions from retrieved, selected teacher notes according to the requested subject, difficulty and question mix. |
| **Validation Agent** | Checks generated question structure and source grounding, including source chunk references, ownership, supporting quotes and requested question distribution. |
| **LangGraph exam workflow** | Coordinates the generation and validation stages. |
| **Document processing and retrieval** | Extracts, chunks, embeds and retrieves relevant note passages, scoped to the teacher and selected documents. |
| **Evaluation workflow** | Evaluates submitted answers and persists resulting marks and feedback. The available handover confirms evaluation integration but does not establish that every evaluator is implemented as a separate LangGraph agent. |

**Source grounding:** The intended question-generation path uses selected teacher notes rather than silently substituting a fixed question bank. The backend uses a configured **Gemini-based embedding/client setup** for document retrieval. Exact model versions, prompts, retries and evaluation rubrics should be checked against the current repository configuration rather than assumed here.

## End-to-end workflow

```text
TEACHER                                         STUDENT
  │                                               │
  ├─ Upload professor notes                       │
  ├─ Select documents                             │
  ├─ Configure exam and question mix              │
  ├─ Generate + validate exam                     │
  └─ Assign division, duration, schedule ────────►│
                                                  ├─ Sign in / see assigned exam
                                                  ├─ Accept consent and check devices
                                                  ├─ Start fullscreen exam
                                                  ├─ Answer questions
                                                  ├─ Webcam/audio recording and
                                                  │  browser/AI monitoring
                                                  └─ Submit or reach exam deadline
                                                       │
                       PostgreSQL results ◄────────────┘
                               │
TEACHER ◄──────────────────────┘
  ├─ Review marks and completion status
  ├─ View Browser Warnings independently
  ├─ View AI Observations independently
  └─ Play recordings / jump near observation times
```

## AI-assisted proctoring

### Browser-security monitoring

The frontend tracks tab switching, fullscreen exits, window focus loss, copying, pasting and right-click/context-menu attempts. The backend keeps a **separate browser-incident count**. The configured exam policy can terminate an attempt after **four counted browser-security incidents**.

### AI video observations

| Observation | Current behavior |
| --- | --- |
| **Face absent** | Detects absence using MediaPipe face detection; an observation and yellow warning are triggered after approximately **5 seconds**. |
| **Face-absence popup** | Displays a warning/beep and keeps the yellow message visible for **at least 10 seconds** after it appears, including when the face returns quickly. |
| **Multiple faces** | Records sustained multiple-face detection after its confirmation threshold (approximately **5 seconds**). |
| **Mobile phone** | Uses TensorFlow.js + COCO-SSD with consecutive positive checks and shows a red warning and beep on a confirmed event. |

**AI observations are saved separately and do not increment the four-incident browser termination counter.** No face recognition or identity verification is performed. Background-speech detection and speech transcription are not enabled.

### Recording and teacher review

- The student's webcam **and microphone audio** are captured with browser `getUserMedia` / `MediaRecorder`.
- Media is uploaded in approximately **10-second chunks** through authenticated exam-attempt endpoints.
- Recordings are kept in private backend storage and retrieved through teacher-authorized endpoints.
- The teacher's **Student Results** table shows separate **Browser Warnings** and **AI Observations** counters, each opening its own review panel.
- AI events include timestamps and available details. **Watch near MM:SS** opens/seeks the exam recording near an event.

> **Video timeline accuracy:** These seek positions are *approximate*. They use exam/event timestamps and detector thresholds, not a frame-accurate recording-start clock. Recorder startup delay or missing chunks can shift the position.

## Technology stack

| Layer | Technology |
| --- | --- |
| Frontend | React, TypeScript, Vite |
| Backend/API | Python, FastAPI |
| Agent orchestration | LangGraph |
| Document retrieval | Text extraction, chunking, embeddings and vector search; Gemini-based client configuration |
| Database | PostgreSQL, SQLAlchemy, Alembic |
| Face detection | MediaPipe Tasks Vision |
| Phone detection | TensorFlow.js, COCO-SSD |
| Video/audio | Browser MediaDevices and MediaRecorder |
| Version control | Git / GitHub |

## Project layout

```text
online_course_exam_agent/
├── backend/
│   └── app/
│       ├── api.py                        # Authentication, exam and proctoring APIs
│       ├── database.py                   # Database setup
│       ├── models.py                     # PostgreSQL ORM models
│       ├── exampilot_persistence.py      # Persistence integration
│       ├── document_processing/         # Text extraction, chunking, retrieval
│       ├── agents/
│       │   ├── question_generation_agent/
│       │   └── validation_agent/
│       ├── graph/
│       │   └── exam_graph.py             # LangGraph workflow
│       └── private_recordings/           # Private media; do not commit
├── frontend/
│   └── src/
│       ├── App.tsx                       # Teacher/student UI and browser monitoring
│       ├── ExamCamera.tsx                # Webcam, audio, recording and observations
│       ├── AIProctor.ts                  # MediaPipe face detection
│       └── PhoneDetector.ts             # TensorFlow phone detection
├── alembic/                              # Database migrations
├── alembic.ini
├── exampilot_timeout_worker.py           # Separate timeout-worker entry point
├── requirements.txt
└── README.md
```

This is a **key-file overview**, not an exhaustive file listing. Some generated directories may not exist until the app is run.

## Local setup

### Prerequisites

- Python environment compatible with `requirements.txt`
- Node.js and npm
- PostgreSQL database
- Backend secrets / API configuration, including Gemini configuration where required
- Browser with webcam and microphone permissions, and MediaRecorder support

### 1. Clone the repository

```powershell
git clone https://github.com/MICHELLE-HOOLGERI25/ExamPilot-Proctored-Examination-System.git
cd ExamPilot-Proctored-Examination-System
```

If the code is currently on `feature/ai-vision-proctoring` rather than the default branch, switch to that branch after cloning.

### 2. Configure backend

Create and activate a Python virtual environment using your preferred Windows shell. From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Configure `DATABASE_URL`, authentication secrets and the Gemini-related settings required by the current backend. The precise variable names should be read from backend configuration or an existing safe example; do **not** commit real `.env` files.

For a new database, review migrations before applying them:

```powershell
alembic upgrade head
```

Start the API:

```powershell
python -m uvicorn backend.app.api:app --reload --host 127.0.0.1 --port 8000
```

### 3. Configure frontend

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal. The frontend uses `http://127.0.0.1:8000` as its development API base unless `VITE_API_BASE_URL` is set.

### 4. Check TypeScript

```powershell
cd frontend
npx tsc --noEmit
```

> The timeout worker is a separate process. Its periodic execution and deployment are not automatically configured by starting the API.

## How to test

1. **Teacher:** sign in; upload supported lecture notes and confirm processing succeeds.
2. **Teacher:** create an exam using selected notes, subject/topic, difficulty and a mix of question types; assign it to a division.
3. **Student:** sign in as a student from the assigned division; start the exam within its permitted schedule.
4. **Student:** consent to camera/microphone recording, enter fullscreen, submit answers and complete the attempt.
5. **Teacher:** open Student Results and confirm marks/status persist.
6. **Proctoring:** separately test browser incidents, five-second face absence, multiple-face detection and phone detection.
7. **Teacher:** check that **Browser Warnings** and **AI Observations** open independent panels and have their own counts.
8. **Teacher:** play the authorized recording with audio and try **Watch near** links.
9. Verify that AI observations **do not** increase the browser termination count.

The student-to-teacher flow and proctoring checks have been manually exercised in local development. Production readiness and security certification have **not** been established.

## Limitations and responsible use

- **Human oversight:** an AI observation is not proof that the student cheated. Educators must review the video and context.
- **Face detection is not face recognition:** the system does not confirm student identity.
- **Detection limitations:** camera positioning, lighting, occlusions and object-detector errors can produce misses or false positives.
- **Browser limitations:** browser-side restrictions cannot guarantee control over another device or all operating-system shortcuts.
- **Recording limitations:** network errors, uploads in flight and missing chunks can affect playback completeness.
- **Timeline limitations:** event-to-recording links are approximate.
- **Speech:** no real-time speech detection or transcription is implemented; microphone audio is part of the consented recording.
- **Privacy:** recordings are sensitive. Define access control, storage security, retention and deletion policies before deploying to real students.
- **Operations:** the timeout worker requires its own reliable scheduling process before being treated as always-on.

## Repository hygiene

Never commit `.env`, local secret files, virtual environments, `node_modules`, database dumps, raw student recordings or `backend/app/private_recordings/`. Review staged files and diffs before committing or pushing.

---

**ExamPilot** — from teacher notes to generated assessment, student examination, automated evaluation, and responsible teacher review. 🎓
