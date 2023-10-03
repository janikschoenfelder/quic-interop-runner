import logging

from threading import Thread
from typing import Union
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from implementations import IMPLEMENTATIONS
from interop import InteropRunner
from pydantic import BaseModel
from testcases import MEASUREMENTS

app = FastAPI()

job_status = {}

# class InteropConfig(BaseModel):
#     name: str
#     description: str | None = None
#     price: float
#     tax: float | None = None


implementations = {
    name: {"image": value["image"], "url": value["url"]}
    for name, value in IMPLEMENTATIONS.items()
}


def run_interop(job_id):
    try:
        quic_measurement = None
        for measurement in MEASUREMENTS:
            if measurement.abbreviation() == "QP":
                quic_measurement = measurement

        InteropRunner(
            implementations=implementations,
            servers=["quiche"],
            clients=["quiche"],
            tests=[],
            measurements=[quic_measurement],
            output="output.json",
            debug=True,
            log_dir="",
            save_files=False,
        ).run()

    except Exception as e:
        # Optional: Fügen Sie Fehlerlogging hier hinzu
        print(f"Error running InteropRunner: {str(e)}")

    finally:
        job_status[job_id] = "completed"


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.post("/start_interop")
async def start_interop():
    # Eindeutige Job-ID erstellen
    for job in job_status:
        if job_status[job] != "completed":
            raise HTTPException(
                status_code=400, detail="Interop runner is already running"
            )
    job_id = str(uuid4())
    logging.debug(job_id)
    job_status[job_id] = "running"
    # InteropRunner in separatem Thread starten
    Thread(target=run_interop, args=(job_id,)).start()
    return {"status": "Interop runner started", "job_id": job_id}


@app.get("/interop_status/{job_id}")
async def get_interop_status(job_id: str):
    # Jobstatus abrufen
    status = job_status.get(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "status": status}
