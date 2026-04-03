# Verification Engine

Session-based document verification engine with extraction, grounding, trust evaluation, and audit-backed decisions.

---

## Overview

This repository contains the core verification pipeline for the Secuura x VIT proof of concept.

The system processes generalized PDF evidence in a session-scoped, privacy-aware workflow. Documents are not processed at upload time; verification starts only when an authorized reviewer opens a session.

The design prioritizes:
- minimal data retention
- deterministic verification logic
- traceable audit outcomes

---

## Key Features

### 1. Session-Based Processing
- One-time upload tokens
- Verification triggered on session open
- No background processing without reviewer action

### 2. Extraction Pipeline
- Dedicated extraction service for safe PDF intake, native parsing, selective OCR, and spatial grounding
- Generalized field candidate extraction, document profiling, PII hints, and credential-ready normalization
- Structured handoff into verification planning, audit overlays, and downstream trust evaluation

### 3. Trust Evaluation Engine
- Connector-based validation flow
- Mock registry / credential connectors for the POC
- Deterministic decision outcomes:
  - Green -> verified by trusted source
  - Amber -> valid document, but no high-assurance confirmation
  - Red -> mismatch, failure, or policy violation

### 4. Audit & Integrity
- Audit receipt persistence in the database layer
- Sealed nonce / receipt schema for tamper-evident records
- Minimal retained metadata after processing

### 5. Privacy-Aware Retention
After session completion:
- transient uploaded content can be cleaned up
- only minimal audit metadata should remain

---

## Repository Structure

  ```text
  verification-engine/
  |
  |-- README.md                         # project overview and onboarding
  |-- LICENSE
  |-- docker-compose.yml                # local multi-service orchestration
  |
  |-- backend/
  |   |-- Dockerfile                    # backend container
  |   |-- requirements.txt              # backend Python dependencies
  |   |
  |   `-- app/
  |       |-- main.py                   # FastAPI entrypoint
  |       |
  |       |-- audit/                    # audit logic and receipt handling
  |       |-- auth/                     # authentication / authorization
  |       |-- cleanup/                  # post-session cleanup
  |       |-- connectors/               # external verification connectors
  |       |   |-- broker.py
  |       |   |-- entra_vc_mock.py
  |       |   `-- vit_mock.py
  |       |-- orchestrator/             # verification orchestration
  |       |-- security/                 # security utilities and policies
  |       |-- sessions/                 # session lifecycle management
  |       |-- storage/                  # transient file / object handling
  |       |-- trust/                    # trust evaluation engine
  |       |-- uploads/                  # upload flow
  |       `-- workflow/                 # end-to-end verification workflow
  |
  |-- extraction/
  |   |-- Dockerfile                    # extraction service container
  |   |-- requirements.txt              # extraction/OCR dependencies
  |   |-- cached_results/               # cached extraction outputs
  |   |-- grounding/                    # PDF field grounding logic
  |   |-- ocr/                          # OCR pipeline
  |   |-- parser/                       # document parsing
  |   |-- samples/                      # sample documents / fixtures
  |   `-- schema/                       # extraction output schemas
  |
  |-- frontend/
  |   |-- Dockerfile                    # frontend container
  |   |-- package.json                  # frontend dependencies and scripts
  |   |
  |   `-- src/
  |       |-- audit_receipt/            # audit receipt UI
  |       |-- components/               # shared UI components
  |       |-- pages/                    # app pages/routes
  |       |-- pdf_viewer/               # PDF viewer and grounding overlays
  |       `-- trust_panel/              # trust decision UI
  |
  |-- db/
  |   |-- audit_schema/                 # audit-related SQL definitions
  |       |-- receipt.sql              # Audit receipt schema
  |       `-- sealed_nonce.sql         # Nonce / integrity schema
  |   `-- workflow_schema/              # workflow/session database schema
  ```

---

## Service Layout

- `backend/`: API and verification orchestration layer
- `backend/app/connectors/`: mocked trust and credential verification connectors used by the POC
- `extraction/`: extraction/OCR service container and dependencies
- `frontend/`: reviewer-facing frontend application
- `db/audit_schema/`: SQL definitions for audit-related persistence

---

## Tech Stack

**Backend**
- FastAPI
- Python dependency set in `backend/requirements.txt`

**Extraction**
- Separate Python service in `extraction/`
- OCR / parsing dependencies isolated from the API service
- FastAPI extraction API exposed from `extraction/main.py`
- Supports PDF text extraction, OCR fallback, and batch CLI processing

**Frontend**
- JavaScript frontend in `frontend/`
- Containerized separately via `frontend/Dockerfile`

**Data / Infra**
- SQL schema under `db/audit_schema/`
- Docker Compose for local multi-service orchestration

---

## Security Model (POC vs Production)

### Implemented in POC
- Session-scoped verification
- Connector-based trust evaluation
- Audit-oriented database schema
- Containerized local deployment

### Documented for Production (not fully implemented here)
- Worker isolation
- stronger key management
- service-to-service hardening
- production-grade orchestration and recovery controls

---

## Limitations

This repository is a proof of concept, not a production system.

- Connectors are mocked
- Some production security controls are architectural goals rather than fully implemented features
- The current repository structure is service-oriented, but still intentionally lightweight for demo use

---

## Goal

The goal of this project is to demonstrate:

- secure document verification workflows
- trust-based decision systems
- privacy-preserving audit design

It is not intended to be a production-ready verification platform.

---

## Extraction Service Quick Start

From `verification-engine/`:

```bash
pip install -r extraction/requirements.txt
uvicorn extraction.main:app --reload
```

Available endpoints:
- `GET /health`
- `POST /extract`
- `POST /extract/batch`

For local CLI extraction:

```bash
python -m extraction.scripts.run_extraction path/to/document.pdf
python -m extraction.scripts.run_extraction path/to/pdf-directory --output-dir path/to/output-json
```

---

## License

Internal POC - Secuura x VIT
