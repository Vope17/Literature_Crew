"""Run the blocking crew outside request handling and persist its progress."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from ai_backend import AIBackendError
from review_guidelines import ReviewOptions, check_review


class ReviewJobs:
    def __init__(self, store):
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="review")

    def submit(self, topic, papers, api_key, model, generate, *, backend="openai_api", cli_timeout=600, options=None):
        options = options or ReviewOptions()
        record_id = self.store.create(kind="review", topic=topic, model=model,
                                      papers=[asdict(paper) for paper in papers],
                                      ai_backend=backend, options=options.model_dump())
        self.executor.submit(self._run, record_id, topic, papers, api_key, model, generate, backend, cli_timeout, options)
        return record_id

    def _run(self, record_id, topic, papers, api_key, model, generate, backend, cli_timeout, options):
        try:
            self.store.progress(record_id, "Starting review…")
            review, evidence = generate(
                topic, papers, api_key, model,
                progress=lambda message: self.store.progress(record_id, message),
                pdf_store=self.store,
                backend=backend, cli_timeout=cli_timeout, options=options,
            )
            self.store.progress(record_id, "Checking citations and evidence coverage…")
            self.store.complete(record_id, review, evidence, checks=check_review(review, evidence))
        except AIBackendError as exc:
            self.store.fail(record_id, str(exc))
        except Exception:
            # Provider exception messages can contain credentials; never persist them.
            self.store.fail(record_id,
                            "Review failed. Check AI settings, login, model access, quota, connection and evidence output, then try again.")

    def shutdown(self):
        self.executor.shutdown(wait=True)
