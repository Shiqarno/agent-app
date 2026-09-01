from fastapi import FastAPI

app = FastAPI(title="Backend")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
