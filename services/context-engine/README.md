# Context engine (Racko CS)

In-memory JSON knowledge base with keyword retrieval. No embeddings.

```powershell
cd services\context-engine
pip install -r requirements.txt
copy .env.example .env
python app.py
```

`SERVICE_PORT` (default 5555) is read by `app.py`. Equivalent:

```powershell
python -m uvicorn app:app --host 0.0.0.0 --port 5555
```

Health: `curl.exe http://localhost:5555/health`

Retrieve: `curl.exe "http://localhost:5555/retrieve?query=refund%20policy"`
