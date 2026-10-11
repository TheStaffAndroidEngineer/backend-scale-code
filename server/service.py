"""Pulse: bounded actual admission queue, worker leases and versioned cache."""

import uuid
import json
from base import BaseService, Problem, fields, integer, text, run


class Service(BaseService):
    KIND = "pulse"

    def seed(self):
        return {"sourceVersion": 1, "jobs": [], "cache": {}, "nextOrder": 1}

    def expire(self, state, now):
        for job in state["jobs"]:
            if job["status"] == "RUNNING" and now >= job["deadline"]:
                job["status"] = "QUEUED"
                job["deadline"] = 0

    def view(self, state, now):
        return state

    def route(self, method, path, body):
        if method == "GET" and path == "/view":
            with self.transaction() as db:
                controls = self.controls(db)
                if controls.get("unavailable"):
                    raise Problem("Fixture unavailable", 503)
                now = self.now(controls)
                state = json.loads(db.execute("SELECT value FROM state WHERE id=1").fetchone()[0])
                self.expire(state, now)
                from base import canonical

                db.execute("UPDATE state SET value=? WHERE id=1", (canonical(state),))
                return 200, {"kind": self.KIND, "observedAt": now, "data": state}, False
        return super().route(method, path, body)

    def apply(self, state, action, args, now):
        self.expire(state, now)
        if action == "request":
            fields(args, {"tenant", "report"})
            tenant = text(args["tenant"], 30)
            report = text(args["report"], 30)
            if tenant not in {"studio", "garden", "market"} or report not in {"weekly", "monthly"}:
                raise Problem("Unknown report scope")
            version = state["sourceVersion"]
            key = f"{tenant}:{report}:{version}"
            if key in state["cache"]:
                return {"accepted": True, "cached": True, "jobId": state["cache"][key]["jobId"]}
            existing = next(
                (
                    j
                    for j in state["jobs"]
                    if j["key"] == key and j["status"] in {"QUEUED", "RUNNING"}
                ),
                None,
            )
            if existing:
                return {"accepted": True, "jobId": existing["id"], "coalesced": True}
            pending = [j for j in state["jobs"] if j["status"] in {"QUEUED", "RUNNING"}]
            if len(pending) >= 4 or sum(j["tenant"] == tenant for j in pending) >= 2:
                return {
                    "accepted": False,
                    "reason": "Capacity is occupied. Check your existing report and retry later with a new request.",
                    "retryAfterMs": 2000,
                }
            if len(state["jobs"]) >= 100:
                return {"accepted": False, "reason": "Fixture history limit reached"}
            job = {
                "id": str(uuid.uuid4()),
                "key": key,
                "tenant": tenant,
                "report": report,
                "sourceVersion": version,
                "order": state["nextOrder"],
                "status": "QUEUED",
                "lease": 0,
                "deadline": 0,
                "result": None,
            }
            state["nextOrder"] += 1
            state["jobs"].append(job)
            return {"accepted": True, "jobId": job["id"]}
        if action == "source":
            fields(args, set())
            state["sourceVersion"] += 1
            return {"accepted": True, "version": state["sourceVersion"]}
        if action == "claim":
            fields(args, set())
            active = next(
                (j for j in state["jobs"] if j["status"] == "RUNNING" and now < j["deadline"]), None
            )
            if active:
                return {"accepted": False, "reason": "The fixture worker is occupied"}
            eligible = [
                j
                for j in state["jobs"]
                if j["status"] == "QUEUED" or (j["status"] == "RUNNING" and now >= j["deadline"])
            ]
            if not eligible:
                return {"accepted": False, "reason": "No queued report"}
            job = min(eligible, key=lambda j: j["order"])
            job["lease"] += 1
            job["deadline"] = now + 10000
            job["status"] = "RUNNING"
            return {
                "accepted": True,
                "jobId": job["id"],
                "lease": job["lease"],
                "sourceVersion": job["sourceVersion"],
            }
        if action == "finish":
            fields(args, {"jobId", "lease"})
            key = text(args["jobId"], 40)
            lease = integer(args["lease"], 1)
            job = next((j for j in state["jobs"] if j["id"] == key), None)
            if (
                not job
                or job["status"] != "RUNNING"
                or job["lease"] != lease
                or now >= job["deadline"]
            ):
                return {"accepted": False, "reason": "Worker lease is no longer current"}
            # Deterministic bounded report represents the immutable input-version snapshot.
            job["result"] = {
                "visits": 120 + job["sourceVersion"] * 7,
                "orders": 18 + job["sourceVersion"] * 2,
            }
            job["status"] = "COMPLETE"
            state["cache"][job["key"]] = {"jobId": job["id"], "result": job["result"]}
            return {"accepted": True, "jobId": job["id"]}
        raise Problem("Unknown action")


if __name__ == "__main__":
    run(Service, 8921)
