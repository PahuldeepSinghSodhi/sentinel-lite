"""End-to-end case API checks without a running Ollama server."""
import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from PyPDF2 import PdfReader
from reportlab.pdfgen import canvas

from app.main import app
from app.evaluation.synthetic import benchmark
from app.vectorstore.faiss_store import FAISSStore


TRANSACTIONS = b"vendor_name,role_level,hourly_rate,transaction_id\nApex,Engineer,125,T-1\nApex,Engineer,100,T-2\n"
RATES = b"vendor_name,role_level,approved_rate\nApex,Engineer,100\n"
DUPLICATE_TRANSACTIONS = (
    b"vendor_name,role_level,hourly_rate,transaction_id\n"
    b"Apex,Engineer,125,T-1\nApex,Engineer,125,T-2\n"
    b"Apex,Engineer,100,T-3\nBeacon,Analyst,90,B-1\nBeacon,Analyst,90,B-2\n"
    b"Cedar,Analyst,80,C-1\n"
)
DUPLICATE_RATES = (
    b"vendor_name,role_level,approved_rate\nApex,Engineer,100\nBeacon,Analyst,90\n"
    b"Cedar,Analyst,80\n"
)


class FakeEmbeddings:
    def embed(self, texts):
        vectors = np.zeros((len(texts), 384), dtype=np.float32)
        vectors[:, 0] = 1.0
        return vectors

    def embed_query(self, query):
        return self.embed([query])


class FakeLLM:
    def generate(self, prompt, **kwargs):
        return "The approved rate is 100, according to the uploaded rate card."


def sample_pdf():
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.drawString(50, 760, "Vendor contract: payment is due in 30 days.")
    pdf.showPage()
    pdf.save()
    return stream.getvalue()


class CaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {"SENTINEL_CASES_DIR": self.directory.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for target, replacement in (
            ("app.main.load_existing_index", FAISSStore()),
            ("app.cases.sources.get_embedding_model", FakeEmbeddings()),
            ("app.rag.pipeline.get_embedding_model", FakeEmbeddings()),
            ("app.rag.pipeline.get_ollama_client", FakeLLM()),
            ("app.rag.multi_doc.get_embedding_model", FakeEmbeddings()),
            ("app.rag.multi_doc.get_ollama_client", FakeLLM()),
        ):
            mock = patch(target, return_value=replacement)
            mock.start()
            self.addCleanup(mock.stop)
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.addCleanup(lambda: self.client_context.__exit__(None, None, None))

    def create(self, name="Test review"):
        response = self.client.post("/cases", json={"name": name})
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def upload(self, case_id, kind, filename, content):
        return self.client.post(f"/cases/{case_id}/files/{kind}",
                                files={"file": (filename, content)})

    def test_validation_gate_and_case_isolation(self):
        first = self.create("First")
        other = self.create("Other")
        self.assertEqual(self.client.post(f"/cases/{first}/start").status_code, 400)
        invalid = self.upload(first, "transactions", "wrong.csv", b"vendor_name\nApex\n")
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("Missing required columns", invalid.json()["detail"])
        self.assertEqual(self.upload(first, "transactions", "tx.csv", TRANSACTIONS).status_code, 200)
        self.assertEqual(self.client.post(f"/cases/{first}/start").status_code, 400)
        duplicate_rates = b"vendor_name,role_level,approved_rate\nApex,Engineer,100\nApex,Engineer,90\n"
        self.assertEqual(self.upload(first, "rate_card", "rates.csv", duplicate_rates).status_code, 400)
        self.assertEqual(self.upload(first, "rate_card", "rates.csv", RATES).status_code, 200)
        self.assertEqual(self.client.post(f"/cases/{first}/start").status_code, 200)
        self.assertEqual(self.client.post(f"/cases/{other}/scans").status_code, 400)
        self.assertEqual(self.client.post(f"/cases/{other}/questions", json={"question": "Rates?"}).status_code, 400)
        self.assertEqual(self.upload(first, "transactions", "tx.csv", TRANSACTIONS).status_code, 400)

    def test_scan_decision_question_sources_and_report(self):
        case_id = self.create()
        self.assertEqual(self.upload(case_id, "transactions", "tx.csv", TRANSACTIONS).status_code, 200)
        self.assertEqual(self.upload(case_id, "rate_card", "rates.csv", RATES).status_code, 200)
        self.assertEqual(self.upload(case_id, "contract", "agreement.pdf", sample_pdf()).status_code, 200)
        self.assertEqual(self.client.post(f"/cases/{case_id}/start").status_code, 200)
        scan = self.client.post(f"/cases/{case_id}/scans")
        self.assertEqual(scan.status_code, 200, scan.text)
        findings = scan.json()["findings"]
        rate = next(item for item in findings if item["type"] == "rate_violation")
        self.assertEqual({e["location"] for e in rate["evidence"]},
                         {"CSV row 2", "CSV row 2, approved_rate column"})
        self.assertEqual(self.client.patch(f"/cases/{case_id}/findings/{rate['id']}",
                                           json={"decision": "approved_exception", "note": ""}).status_code, 400)
        decision = self.client.patch(f"/cases/{case_id}/findings/{rate['id']}",
                                     json={"decision": "approved_exception", "note": "VP approved"})
        self.assertEqual(decision.status_code, 200)
        question = self.client.post(f"/cases/{case_id}/questions", json={"question": "What is the approved rate?", "top_k": 10})
        self.assertEqual(question.status_code, 200, question.text)
        self.assertTrue(any(source.get("page") == 1 for source in question.json()["sources"]))
        excerpt = self.client.get(f"/cases/{case_id}/source/contract", params={"page": 1})
        self.assertIn("30 days", excerpt.json()["text"])
        second_scan = self.client.post(f"/cases/{case_id}/scans")
        self.assertEqual(second_scan.status_code, 200)
        saved = self.client.get(f"/cases/{case_id}").json()
        self.assertEqual(len(saved["scans"]), 2)
        self.assertEqual(saved["scans"][0]["findings"][-1]["decision"], "approved_exception")
        self.assertIsNone(saved["scans"][1]["findings"][-1]["decision"])
        exported = self.client.get(f"/cases/{case_id}/report")
        self.assertEqual(exported.status_code, 200)
        pages = PdfReader(io.BytesIO(exported.content)).pages
        text = "\n".join(page.extract_text() for page in pages)
        for expected in ("Anomaly review", "Document intelligence", "VP approved", "Question 1", "rates.csv"):
            self.assertIn(expected, text)

    def test_unlisted_vendor_is_flagged(self):
        case_id = self.create()
        data = b"vendor_name,role_level,hourly_rate\nUnlisted Vendor,Engineer,140\n"
        self.assertEqual(self.upload(case_id, "transactions", "unknown.csv", data).status_code, 200)
        self.assertEqual(self.upload(case_id, "rate_card", "rates.csv", RATES).status_code, 200)
        self.assertEqual(self.client.post(f"/cases/{case_id}/start").status_code, 200)
        result = self.client.post(f"/cases/{case_id}/scans")
        self.assertEqual(result.status_code, 200, result.text)
        finding = next(item for item in result.json()["findings"] if item["type"] == "missing_rate")
        self.assertEqual(finding["evidence"][0]["location"], "CSV row 2")

    def test_reason_endpoint_uses_embedding_wrapper(self):
        response = self.client.post("/reason", json={"question": "Compare the contract and rate card"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["reasoning_chain"])

    def test_sample_case_can_start_without_manual_upload(self):
        response = self.client.post("/cases/demo")
        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(response.json()["ready"])
        self.assertEqual(set(response.json()["files"]), {"transactions", "rate_card", "contract"})
        case_id = response.json()["id"]
        source = self.client.get(f"/cases/{case_id}/source/contract",
                                 params={"line_start": 1, "line_end": 1})
        self.assertEqual(source.status_code, 200)
        self.assertEqual(source.json()["location"], "lines 1-1")

    def test_large_case_scans_and_exports(self):
        transactions, rates, _ = benchmark()
        case_id = self.create("240-row review")
        self.assertEqual(self.upload(case_id, "transactions", "benchmark.csv",
                                     transactions.to_csv(index=False).encode()).status_code, 200)
        self.assertEqual(self.upload(case_id, "rate_card", "rates.csv",
                                     rates.to_csv(index=False).encode()).status_code, 200)
        self.assertEqual(self.client.post(f"/cases/{case_id}/start").status_code, 200)
        scan = self.client.post(f"/cases/{case_id}/scans")
        self.assertEqual(scan.status_code, 200, scan.text)
        self.assertEqual(scan.json()["transactions_analyzed"], 240)
        self.assertGreater(len(scan.json()["findings"]), 0)
        self.assertEqual(self.client.get(f"/cases/{case_id}/report").status_code, 200)

    def test_questions_use_latest_scan_exact_counts_and_source_rows(self):
        case_id = self.create("Cross-section review")
        other = self.create("Separate review")
        for target in (case_id, other):
            self.assertEqual(self.upload(target, "transactions", "tx.csv", DUPLICATE_TRANSACTIONS).status_code, 200)
            self.assertEqual(self.upload(target, "rate_card", "rates.csv", DUPLICATE_RATES).status_code, 200)
            self.assertEqual(self.client.post(f"/cases/{target}/start").status_code, 200)

        before = self.client.post(f"/cases/{case_id}/questions", json={"question": "How many duplicates?"})
        self.assertEqual(before.status_code, 200)
        self.assertIn("No anomaly scan", before.json()["answer"])
        self.assertFalse(before.json()["sources"])

        first_scan = self.client.post(f"/cases/{case_id}/scans")
        self.assertEqual(first_scan.status_code, 200, first_scan.text)
        question = self.client.post(f"/cases/{case_id}/questions", json={
            "question": "How many duplicates are there and which company has which duplicate?"})
        self.assertEqual(question.status_code, 200, question.text)
        answer = question.json()
        self.assertIn("2 duplicate group(s), 4 transaction row(s) involved, and 2 additional copy/copies", answer["answer"])
        self.assertEqual(answer["presentation"]["kind"], "scan")
        self.assertEqual([metric["value"] for metric in answer["presentation"]["metrics"]], [2, 4, 2])
        self.assertEqual({group["vendor"] for group in answer["presentation"]["groups"]}, {"Apex", "Beacon"})
        self.assertIn("Apex", answer["answer"])
        self.assertIn("Beacon", answer["answer"])
        self.assertEqual({source["row_number"] for source in answer["sources"]}, {2, 3, 5, 6})
        self.assertEqual(answer["confidence"]["scan_id"], first_scan.json()["id"])
        row = self.client.get(f"/cases/{case_id}/source/transactions", params={"row": 3})
        self.assertEqual(row.status_code, 200)
        self.assertIn("Apex", row.json()["text"])

        apex = self.client.post(f"/cases/{case_id}/questions", json={
            "question": "Which duplicate rows belong to Apex?"}).json()
        self.assertIn("1 duplicate group(s), 2 transaction row(s)", apex["answer"])
        self.assertNotIn("Beacon", apex["answer"])
        self.assertEqual({source["row_number"] for source in apex["sources"]}, {2, 3})
        no_matches = self.client.post(f"/cases/{case_id}/questions", json={
            "question": "Which duplicate rows belong to Cedar?"}).json()
        self.assertEqual(no_matches["confidence"]["basis"], "latest_scan")
        self.assertIn("0 duplicate group(s), 0 transaction row(s)", no_matches["answer"])
        self.assertFalse(no_matches["sources"])

        separate = self.client.post(f"/cases/{other}/questions", json={"question": "How many duplicates?"}).json()
        self.assertIn("No anomaly scan", separate["answer"])
        second_scan = self.client.post(f"/cases/{case_id}/scans").json()
        latest = self.client.post(f"/cases/{case_id}/questions", json={"question": "How many duplicates?"}).json()
        self.assertEqual(latest["confidence"]["scan_id"], second_scan["id"])
        self.assertEqual(question.json()["confidence"]["scan_id"], first_scan.json()["id"])
        saved_question = self.client.get(f"/cases/{case_id}").json()["questions"][1]
        self.assertEqual(saved_question["presentation"], answer["presentation"])

        exported = self.client.get(f"/cases/{case_id}/report")
        pages = PdfReader(io.BytesIO(exported.content)).pages
        text = "\n".join(page.extract_text() for page in pages)
        self.assertIn("2 duplicate group(s)", text)
        self.assertIn("CSV row 3", text)

    def test_question_combines_findings_and_contract_passages(self):
        case_id = self.create("Combined context")
        self.upload(case_id, "transactions", "tx.csv", DUPLICATE_TRANSACTIONS)
        self.upload(case_id, "rate_card", "rates.csv", DUPLICATE_RATES)
        self.upload(case_id, "contract", "agreement.pdf", sample_pdf())
        self.client.post(f"/cases/{case_id}/start")
        self.client.post(f"/cases/{case_id}/scans")
        response = self.client.post(f"/cases/{case_id}/questions", json={
            "question": "How many duplicates are there and what does the contract say about payment terms?"})
        self.assertEqual(response.status_code, 200, response.text)
        answer = response.json()
        self.assertIn("2 duplicate group(s)", answer["answer"])
        self.assertIn("Uploaded-document context", answer["answer"])
        self.assertIn("approved rate", answer["presentation"]["document_answer"])
        self.assertTrue(any(source.get("kind") == "transactions" for source in answer["sources"]))
        self.assertTrue(any(source.get("page") == 1 for source in answer["sources"]))

    def test_existing_question_table_is_migrated_without_losing_answers(self):
        path = Path(self.directory.name) / "cases.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            db.execute("""CREATE TABLE questions (
                id TEXT PRIMARY KEY, case_id TEXT NOT NULL, created_at TEXT NOT NULL,
                question TEXT NOT NULL, answer TEXT NOT NULL, sources_json TEXT NOT NULL,
                confidence_json TEXT NOT NULL)""")
            db.execute("INSERT INTO questions VALUES (?, ?, ?, ?, ?, ?, ?)",
                       ("old-question", "legacy-case", "2026-01-01", "Old question", "Old answer", "[]", "{}"))
            db.commit()
        self.create()
        with closing(sqlite3.connect(path)) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(questions)")}
            old = db.execute("SELECT answer, presentation_json FROM questions WHERE id = 'old-question'").fetchone()
        self.assertIn("presentation_json", columns)
        self.assertEqual(old, ("Old answer", None))


if __name__ == "__main__":
    unittest.main()
