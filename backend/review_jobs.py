"""Run the blocking crew outside request handling and persist its progress."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict


class ReviewJobs:
    def __init__(self, store):
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="review")

    def submit(self, topic, papers, api_key, model, generate):
        record_id = self.store.create(kind="review", topic=topic, model=model,
                                      papers=[asdict(paper) for paper in papers])
        self.executor.submit(self._run, record_id, topic, papers, api_key, model, generate)
        return record_id

    def _run(self, record_id, topic, papers, api_key, model, generate):
        try:
            self.store.progress(record_id, "Starting review…")
            review, evidence = generate(
                topic, papers, api_key, model,
                progress=lambda message: self.store.progress(record_id, message),
                pdf_store=self.store,
            )
            self.store.complete(record_id, review, evidence)
        except Exception:
            # Provider exception messages can contain credentials; never persist them.
            self.store.fail(record_id,
                            "Review failed. Check your API key, model access, quota, and connection, then try again.")

    def shutdown(self):
        self.executor.shutdown(wait=True)
