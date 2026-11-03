"""Load test: officers reading dashboards while owners upload statements.

Run with ops/load/run.sh, which prepares a database with six months of data and starts the
stack. Rate limits are raised for the run: this measures the application, not the limiter.

  OfficerUser (weight 4): overview metrics, the review queue, transaction pages, a flag.
  OwnerUser   (weight 1): uploads a freshly generated one-week statement, then polls its status
                          the way the UI does (every 2 s) until the pipeline finishes.
"""

from __future__ import annotations

import os
import random
import uuid
from datetime import date, timedelta

from locust import HttpUser, between, task

from khataiq.pipeline.parsers.demo_csv import render_demo_csv

PASSWORD = "khataiq-dev-password"
BUSINESS_ID = int(os.environ.get("LOAD_BUSINESS_ID", "1"))
ACCOUNT_ID = int(os.environ.get("LOAD_ACCOUNT_ID", "1"))


def login(user: HttpUser, email: str) -> None:
    response = user.client.post("/v1/auth/login", json={"email": email, "password": PASSWORD},
                                name="/v1/auth/login")
    token = response.json()["access_token"]
    user.client.headers["Authorization"] = f"Bearer {token}"


class OfficerUser(HttpUser):
    weight = 4
    wait_time = between(0.5, 2)

    def on_start(self) -> None:
        login(self, f"officer{random.randint(1, 3)}@demo.khataiq.dev")

    @task(4)
    def overview(self) -> None:
        self.client.get(f"/v1/businesses/{BUSINESS_ID}", name="/v1/businesses/{id}")
        self.client.get(f"/v1/businesses/{BUSINESS_ID}/metrics", name="/v1/businesses/{id}/metrics")

    @task(3)
    def transactions(self) -> None:
        self.client.get(f"/v1/businesses/{BUSINESS_ID}/transactions?limit=100",
                        name="/v1/businesses/{id}/transactions")

    @task(2)
    def review_queue(self) -> None:
        flags = self.client.get("/v1/flags?status=open", name="/v1/flags").json()["items"]
        if flags:
            self.client.get(f"/v1/flags/{flags[0]['id']}", name="/v1/flags/{id}")

    @task(1)
    def graph(self) -> None:
        self.client.get(f"/v1/businesses/{BUSINESS_ID}/graph", name="/v1/businesses/{id}/graph")


class OwnerUser(HttpUser):
    weight = 1
    wait_time = between(5, 15)

    def on_start(self) -> None:
        login(self, "owner1@demo.khataiq.dev")

    @task
    def upload_statement(self) -> None:
        start = date(2027, 1, 1) + timedelta(days=random.randint(0, 3000))
        rows = [(start + timedelta(days=d), f"UPI/LOAD {uuid.uuid4().hex[:8]}/x{d}@okaxis",
                 0, random.randint(10_000, 500_000)) for d in range(7)]
        response = self.client.post(
            f"/v1/accounts/{ACCOUNT_ID}/uploads", name="/v1/accounts/{id}/uploads",
            files={"file": ("statement.csv", render_demo_csv(1_000_000, rows), "text/csv")},
            headers={"Idempotency-Key": str(uuid.uuid4())})
        upload_id = response.json()["id"]
        for _ in range(30):
            status = self.client.get(f"/v1/uploads/{upload_id}", name="/v1/uploads/{id}").json()
            if status["status"] in ("processed", "needs_review", "failed"):
                break
            self._sleep(2)

    def _sleep(self, seconds: float) -> None:
        import gevent

        gevent.sleep(seconds)
