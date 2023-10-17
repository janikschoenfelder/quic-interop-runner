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

opt_servers = [
    # "lsquic",
    "quiche"
]
opt_clients = [
    # "lsquic",
    "quiche"
]

ls_params = {
    "-o cc_algo": {
        "values": [
            0,
            1,
            2,
            3,
        ],  # 0: use default (adaptive), 1: cubic, 2: bbr1, 3: adaptive
        "type": "categorical",
        "for": "both",
        "default": 0,
    },
    "-o cfcw": {
        "default": 16384,
        "type": "integer",
        "range": [16384, 16384 * 2 * 2 * 2],
        "for": "both",
    },
    "-o sfcw": {
        "default": 16384,
        "type": "integer",
        "range": [16384, 16384 * 2 * 2 * 2],
        "for": "both",
    },
    "-o init_max_data": {
        "default": 10000000,
        "type": "integer",
        "range": [10000000, 10000000 * 1.6],
        "for": "both",
    },
    "-o max_cfcw": {
        "default": 25165824,
        "type": "integer",
        "range": [25165824 * 0.8, 25165824 * 0.8],
        "for": "both",
    },
    "-o max_sfcw": {
        "default": 16777216,
        "type": "integer",
        "range": [16384, 16384 * 2 * 2 * 2],
        "for": "both",
    },
    "-o init_max_streams_bidi": {
        "default": 100,
        "type": "integer",
        "range": [100 * 0.8, 100 * 1.2],
        "for": "both",
    },
    "-o init_max_streams_uni": {
        "default": 100,
        "type": "integer",
        "range": [100 * 0.8, 100 * 1.2],
        "for": "both",
    },
    "-o init_cwnd": {
        "default": 10,
        "type": "integer",
        "range": [10 * 0.8, 10 * 1.2],
        "for": "both",
    },
}


quiche_params = {
    "--cc-algorithm": {
        "values": ["bbr", "bbr2", "cubic", "reno"],
        "type": "categorical",
        "for": "both",
        "default": "cubic",
    },
    "--max-data": {
        "default": 10000000,
        "type": "integer",
        "range": [10000000, 16 * 1024 * 1024],
        "for": "both",
    },
    "--max-window": {
        "default": 25165824,
        "type": "integer",
        "range": [25165824 * 0.8, 25165824 * 1.2],
        "for": "both",
    },
    "--max-stream-data": {
        "default": 1000000,
        "type": "integer",
        "range": [1000000 * 0.7, 2000000],
        "for": "both",
    },
    "--max-stream-window": {
        "default": 16777216,
        "type": "integer",
        "range": [16777216 * 0.7, 16777216 * 1.3],
        "for": "both",
    },
    "--max-streams-bidi": {
        "default": 100,
        "type": "integer",
        "range": [100 * 0.8, 100 * 1.2],
        "for": "both",
    },
    "--max-streams-uni": {
        "default": 100,
        "type": "integer",
        "range": [100 * 0.8, 100 * 1.2],
        "for": "both",
    },
    "--initial-cwnd-packets": {
        "default": 10,
        "type": "integer",
        "range": [10 * 0.8, 10 * 1.2],
        "for": "both",
    },
}

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
            servers=opt_servers,
            clients=opt_clients,
            tests=[],
            measurements=[quic_measurement],
            output="output.json",
            debug=True,
            log_dir="",
            save_files=False,
            parameters={"lsquic": ls_params, "quiche": quiche_params},
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
    # check if running qir
    for job in job_status:
        if job_status[job] != "completed":
            raise HTTPException(
                status_code=400, detail="Interop runner is already running"
            )

    # unique id
    job_id = str(uuid4())
    logging.debug(job_id)

    # start QIR in thread
    Thread(target=run_interop, args=(job_id,)).start()
    job_status[job_id] = "running"
    return {"status": "Interop runner started", "job_id": job_id}


@app.get("/interop_status/{job_id}")
async def get_interop_status(job_id: str):
    status = job_status.get(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "status": status}
