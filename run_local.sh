#!/bin/bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export GOOGLE_API_KEY="your_actual_key_here"
export GEMINI_API_KEY="your_actual_key_here"
export VERIFIER_LOCAL_VERIFICATION_STORE_PATH="app/verifier_providers/fixtures/local_verification_records.json"
export ENABLE_LOCAL_MOCK_VERIFIERS="true"
export PYTHONPATH=$PYTHONPATH:.
python -m app.main
