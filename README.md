# Team 03 – B Division | Agentic AI

This repository contains the **VII Semester Agentic AI course work** for **Team 03 – B Division**, including the completed course assignments and the team's course project.

---

## 📚 Contents

This repository is organized into two major sections:

- **Agentic AI Assignments**
- **Online Course Examination System – Course Project**

---

# 1. Agentic AI Assignments

The **Assignments** section contains the coursework and practical assignments completed as part of the VII Semester **Agentic AI** course.

The assignments cover the concepts, techniques, and implementations studied throughout the course.

### Assignment Repository

The complete assignment work is available in the following repository:

**Agentic Assignment Repository:**  
https://github.com/tanujaratan/Agentic-Assignment

The assignments are maintained as part of the team's Agentic AI coursework.

---

# 2. Online Course Examination System

## 📌 Course Project

### Online Course Examination System

The **Online Course Examination System** is an Agentic AI-based course project designed to support the online examination lifecycle.

The system combines online examination functionality with **Agentic AI** and **AI-based vision proctoring** to provide an intelligent and monitored examination environment.

### Key Areas

- Online examination management
- Question-bank based examination
- Practice sessions
- Subject and difficulty-based question handling
- Examination session management
- Automated evaluation
- Agentic AI-based examination workflows
- AI Vision Proctoring
- Computer-vision based examination monitoring

---

## 🤖 Agentic AI

The system uses an agent-oriented approach for handling examination-related tasks and workflows.

The project is designed to automate different stages of the examination process rather than functioning only as a conventional chatbot.

The Agentic AI components support examination-related operations such as:

- Question retrieval and handling
- Practice session creation
- Examination workflow management
- Evaluation
- Examination-related processing

---

## 👁️ AI Vision Proctoring

The project also includes an **AI Vision Proctoring** component for monitoring candidates during online examinations.

The proctoring implementation uses browser-based computer vision technologies to process camera input and detect events that may indicate suspicious examination activity.

### Technologies Used

- **MediaPipe**
- **COCO-SSD**
- **TensorFlow.js**
- **FastAPI**

The AI Vision Proctoring implementation is available in the project's:

```text
feature/ai-vision-proctoring
```

branch.

---

## 🏗️ High-Level Architecture

```text
                         ONLINE COURSE EXAMINATION SYSTEM
                                      │
                                      ▼
                              ┌───────────────┐
                              │   Student UI  │
                              └───────┬───────┘
                                      │
                                      ▼
                              ┌───────────────┐
                              │    FastAPI    │
                              │    Backend    │
                              └───────┬───────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                    ▼                 ▼                 ▼
             ┌────────────┐   ┌──────────────┐   ┌──────────────┐
             │ Question   │   │ Examination  │   │ AI Vision    │
             │ Management │   │  Management  │   │  Proctoring  │
             └────────────┘   └──────────────┘   └──────────────┘
                    │                 │                 │
                    └─────────────────┼─────────────────┘
                                      ▼
                              ┌───────────────┐
                              │  Evaluation   │
                              │ & Monitoring  │
                              └───────────────┘
```

---

## 🛠️ Technology Stack

### Backend
- Python
- FastAPI

### Agentic AI
- Agentic AI workflows
- AI-based examination components

### AI Vision Proctoring
- MediaPipe
- COCO-SSD
- TensorFlow.js
- Computer Vision

### Frontend
- HTML
- CSS
- JavaScript

### Development & Version Control
- Git
- GitHub

---

## 🔗 Original Course Project Repository

The original course project repository is:

**ExamPilot – Proctored Examination System**

https://github.com/MICHELLE-HOOLGERI25/ExamPilot-Proctored-Examination-System

The `feature/ai-vision-proctoring` branch contains the AI Vision Proctoring implementation.

---

## 🚀 Getting Started

### Prerequisites

Install the required development tools:

- Python 3.x
- Git
- Node.js and npm, if required by the frontend

### Clone this repository

```bash
git clone <TEAM-03-REPOSITORY-URL>
cd Online-Course-Examination-System-Team03-B-Div
```

### Install Python dependencies

```bash
python -m venv venv
```

Activate the environment on Windows:

```bash
venv\Scripts\activate
```

Then:

```bash
pip install -r requirements.txt
```

Follow the project-specific instructions for starting the backend and frontend.

---

## 🔐 Environment Variables

API keys, credentials, and other sensitive configuration values should be stored in environment variables and **must not be committed to GitHub**.

For example:

```text
.env
```

Make sure sensitive files are excluded using `.gitignore`.

---

## 📁 Repository Organization

```text
Team03-B-Div-Online-Course-Examination-System/
│
├── Assignments/
│   └── Agentic AI course assignments
│
├── Course-Project/
│   └── Online Course Examination System
│
├── README.md
├── requirements.txt
└── .gitignore
```

> The final directory structure may be updated according to the files included in the repository.

---

## 📌 Project Status

This repository is maintained as the combined submission space for **Team 03 – B Division** for the VII Semester Agentic AI course.

It brings together:

- Agentic AI course assignments
- Online Course Examination System course project
- AI Vision Proctoring implementation
- Project documentation and supporting resources

---

**VII Semester – Agentic AI**  
**Team 03 – B Division**
