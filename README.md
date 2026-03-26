# Verification Engine

Session-based document verification engine with extraction, grounding, trust evaluation, and audit-backed decisions.

---

## Overview

This repository implements the core verification pipeline for the Secuura × VIT Proof of Concept.

The system processes recruitment documents (PDFs) in a **session-scoped, privacy-aware workflow**.  
Documents are **not processed at upload time** — verification is triggered only when an authorized reviewer opens a session.

The design prioritizes:
- minimal data retention
- deterministic verification logic
- traceable audit outcomes

---

## Key Features

### 1. Session-Based Processing
- One-time upload tokens
- Verification triggered on session open (deferred execution)
- No background processing without user action

### 2. Extraction Pipeline
- Text-based PDF parsing (PyMuPDF / pdfplumber)
- Local OCR fallback (Tesseract / PaddleOCR)
- Canonical field mapping

### 3. Spatial Grounding
- Extracted values linked to PDF coordinates
- Reviewer can see **where data came from**
- Normalized bounding boxes rendered via PDF.js

### 4. Trust Evaluation Engine
- Connector-based validation (VIT registry mock, VC mock)
- Deterministic decision model:
  - **Green** → verified by trusted source
  - **Amber** → valid document, no high-assurance source
  - **Red** → mismatch, failure, or policy violation

### 5. Audit & Integrity
- HMAC-based document commitment
- Signed audit receipt
- Pseudonymous reviewer references
- No raw document stored after session

### 6. Content-Minimised Retention
After session completion:
- PDF deleted
- extracted data deleted
- OCR output deleted
- only minimal audit metadata retained

---

## System Flow

1. Reviewer creates session  
2. One-time upload token issued  
3. PDF uploaded to transient storage  
4. Reviewer opens session → verification starts  
5. Extraction + grounding executed  
6. Connector validation performed  
7. Trust engine produces outcome  
8. Audit receipt generated  
9. Cleanup deletes all content  

---

## Tech Stack

**Backend**
- FastAPI
- PostgreSQL (session state + audit store)
- PyMuPDF / pdfplumber
- Tesseract / PaddleOCR

**Frontend**
- React
- PDF.js (viewer + grounding overlay)

**Infrastructure (POC)**
- Docker Compose (single machine)
- Environment-based secrets
- Local execution (no external APIs required)

---

## Repository Structure

verification-engine/
│
├── backend/
│   ├── services/        # extraction, grounding, audit, cleanup
│   ├── connectors/      # VIT mock, VC mock
│   ├── models/          # schemas (Pydantic)
│   ├── routes/          # API endpoints
│   └── db/              # database access
│
├── frontend/
│   ├── components/      # PDF viewer, grounding UI
│   └── pages/
│
├── fixtures/
│   └── vit_registry.json
│
├── docker-compose.yml
└── README.md

---

## Security Model (POC vs Production)

### Implemented in POC
- One-time upload tokens
- Input validation and PDF safety checks
- Pseudonymous audit records
- Content deletion after session

### Documented for Production (not implemented)
- Worker isolation (tmpfs, swap-disabled execution)
- KMS-backed encryption
- mTLS between services
- HSM-backed audit recovery vault
- Kubernetes-based worker orchestration

---

## Limitations (Important)

This is a **proof of concept**, not a production system.

- Processing runs in-process (no isolated workers)
- Cleanup is best-effort (no distributed retry controller)
- OCR and extraction accuracy depend on input quality
- Connectors are mocked (no real registry integration)

---

## Demo Notes

To ensure reliability during demo:
- Preprocess selected PDFs (extraction + grounding)
- Cache results before presentation
- Run trust evaluation and audit flow live

---

## Goal

The goal of this project is to demonstrate:

- secure document verification workflows  
- trust-based decision systems  
- privacy-preserving audit design  

—not to provide a production-ready verification platform.

---

## License

Internal POC — Secuura × VIT
