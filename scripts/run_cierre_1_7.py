# -*- coding: utf-8 -*-
"""Ejecutor universal, reanudable y auditable de la ruta RECYM 1..7."""
from __future__ import print_function

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core.context_identity import build_context_identity, context_fingerprint
from pipeline.run_evidence import RunEvidence


class ApiError(RuntimeError):
    pass


class ApiClient(object):
    def __init__(self, base_url, identity, api_key=None, timeout=180):
        self.base_url = base_url.rstrip("/")
        self.identity = dict(identity)
        self.timeout = timeout
        self.headers = {
            "Content-Type": "application/json",
            "X-Feeder": self.identity["feeder_id"],
            "X-Database-Mdb": self.identity["database_mdb"],
            "X-Study-Path": self.identity["study_path"],
        }
        if api_key:
            self.headers["X-API-Key"] = api_key

    def request(self, method, path, body=None, timeout=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=dict(self.headers),
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as ex:
            raw = ex.read().decode("utf-8", "replace")
            raise ApiError("HTTP %s %s: %s" % (ex.code, path, raw[:800]))
        except Exception as ex:
            raise ApiError("%s %s: %s" % (method, path, ex))
        try:
            result = json.loads(raw)
        except Exception:
            raise ApiError("Respuesta no JSON de %s: %s" % (path, raw[:500]))
        if isinstance(result, dict) and result.get("ok") is False:
            raise ApiError("%s: %s" % (
                result.get("error_code") or path,
                result.get("error") or result.get("msg") or "respuesta ok=false",
            ))
        return result

    def job(self, action, payload, timeout=900, poll=1.0):
        body = {
            "action": action,
            "feeder": self.identity["feeder_id"],
            "payload": dict(self.identity, **payload),
        }
        created = self.request("POST", "/api/jobs", body, timeout=60)
        job_id = created.get("job_id")
        if not job_id:
            raise ApiError("La API no devolvio job_id para %s" % action)
        started = time.time()
        while time.time() - started < timeout:
            response = self.request("GET", "/api/jobs/%s" % job_id, timeout=60)
            job = response.get("job") or response
            status = str(job.get("status") or "")
            if status == "ok":
                result = job.get("result") or job
                if isinstance(result, dict) and result.get("ok") is False:
                    raise ApiError("%s: %s" % (
                        result.get("error_code") or action,
                        result.get("error") or result.get("msg") or "job fallo",
                    ))
                if isinstance(result, dict):
                    result = dict(result)
                    result.setdefault("job_id", job_id)
                    result.setdefault("job_action", action)
                return result
            if status == "error":
                result = job.get("result") or {}
                raise ApiError("%s: %s" % (
                    result.get("error_code") or action,
                    result.get("error") or job.get("message") or "job error",
                ))
            time.sleep(poll)
        raise ApiError("Timeout %ss en job %s (%s)" % (timeout, job_id, action))


def _load_json(path):
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _assert_context(result, identity):
    if not isinstance(result, dict):
        return
    supplied = result.get("context_fingerprint")
    if supplied and supplied != identity["context_fingerprint"]:
        raise ApiError("CONTEXT_IDENTITY_MISMATCH en respuesta")


class UniversalRunner(object):
    def __init__(self, client, evidence, allow_write=False, allow_optimization=False,
                 stage4_rows=None):
        self.client = client
        self.evidence = evidence
        self.identity = client.identity
        self.allow_write = bool(allow_write)
        self.allow_optimization = bool(allow_optimization)
        self.stage4_rows = stage4_rows

    def _execute(self, stage, fn, write=False, stop=True):
        if stage in self.evidence.completed_stages():
            return True
        if write and not self.allow_write:
            self.evidence.append(stage, "pending_real", "Requiere --allow-write")
            return True
        try:
            result = fn()
            _assert_context(result, self.identity)
            self.evidence.append(stage, "passed", "Compuerta verificada", result=result)
            print("[OK] %s" % stage)
            return True
        except Exception as ex:
            self.evidence.append(stage, "failed", str(ex))
            print("[FAIL] %s: %s" % (stage, ex))
            if stop:
                raise
            return False

    def run(self):
        i = self.identity
        run_id = self.evidence.run_id
        common = dict(i, run_id=run_id)

        self._execute("0.route", lambda: self.client.request("GET", "/api/ui/ping"))
        self._execute("1.discovery", lambda: self.client.job(
            "contexto_descubrir_redes", {"database_mdb": i["database_mdb"]}, timeout=300,
        ))
        self._execute("1.1", lambda: self.client.request("POST", "/api/contexto/aplicar", dict(
            common, feeder=i["feeder_id"], strict=True,
            allowed_networks=[i["network_id"]],
        ), timeout=300), write=True)

        def save_head():
            head = self.client.request("GET", "/api/cabecera?" + urllib.parse.urlencode({
                "feeder": i["feeder_id"],
            }))
            if head.get("P_kW") in (None, "") or head.get("Q_kvar") in (None, ""):
                raise ApiError("CABECERA_INPUT_REQUIRED: cargue medicion real antes de 1.2")
            body = dict(common, feeder=i["feeder_id"], mode=head.get("mode") or "PQ")
            for key in ("P_kW", "Q_kvar", "cosfi", "I_A", "Vll_kV", "Va_kV", "Vb_kV",
                        "Vc_kV", "S_kVA", "P_avg_kW", "factor_carga_pct", "medidor",
                        "medicion_file", "fecha_medicion"):
                if head.get(key) not in (None, ""):
                    body[key] = head[key]
            result = self.client.request("POST", "/api/cabecera", body, timeout=420)
            if not (result.get("study_saved") and result.get("db_updated") and result.get("project_saved")):
                raise ApiError("CABECERA_NOT_PHYSICALLY_COMMITTED")
            return result

        self._execute("1.2", save_head, write=True)
        self._execute("2.1", lambda: self.client.job("calidad_diagnosticar", common, timeout=900))
        self._execute("2.2", lambda: self.client.job("calidad_proponer", common, timeout=600))
        self._execute("2.3", lambda: self.client.job("calidad_aplicar", common, timeout=900), write=True)
        self._execute("2.4", lambda: self.client.job("calidad_convergencia", common, timeout=600))

        files = {}
        def clients_table():
            files.update(self.client.request("GET", "/api/clientes/archivos"))
            supply = (files.get("suministro") or [None])[0]
            clients = (files.get("clientesimportantes") or [None])[0]
            if not supply or not clients:
                raise ApiError("CLIENT_FILES_REQUIRED")
            return self.client.request("POST", "/api/clientes/tabla", dict(
                common, feeder=i["feeder_id"], feeders=[i["feeder_id"]],
                suministro=supply, clientesimportantes=clients, rebuild=False,
            ), timeout=300)

        self._execute("3.1", clients_table)
        self._execute("3.2", lambda: self.client.request("POST", "/api/clientes/aplicar", dict(
            common, feeder=i["feeder_id"], feeders=[i["feeder_id"]],
            suministro=(files.get("suministro") or [None])[0],
            clientes_file=(files.get("clientesimportantes") or [None])[0],
        ), timeout=600), write=True)
        self._execute("3.3", lambda: self.client.job("distribucion", common, timeout=1200), write=True)
        self._execute("3.4", lambda: self.client.job("flujo_situacional_34", common, timeout=1200), write=True)

        self._execute("4.1", lambda: self.client.request(
            "POST", "/api/nodos/inventario", dict(common, refresh=True), timeout=300,
        ))
        if self.stage4_rows:
            self._execute("4.2", lambda: self.client.request(
                "POST", "/api/cargas/lote/conectar", dict(common, rows=self.stage4_rows), timeout=1200,
            ), write=True)
        else:
            connected = self.client.request("GET", "/api/cargas/conectadas")
            if not connected.get("rows"):
                self.evidence.append("4.2", "blocked", "Falta --stage4-json; no se inventan cargas")
                raise ApiError("STAGE4_INPUT_REQUIRED")
            self.evidence.append("4.2", "passed", "Se verificaron cargas existentes", result=connected)

        self._execute("5.1", lambda: self.client.job("flujo", dict(
            common, scenario="proyectado", update_informe=False,
        ), timeout=1200), write=True)
        self._execute("6.1", lambda: self.client.request("POST", "/api/informe/armar", dict(
            common, fill=True, ensure_lf=False, force_captures=False, require_delivery=True,
        ), timeout=1200), write=True)
        self._execute("6.2", lambda: self.client.request("GET", "/api/informe/status"))
        self._execute("7.1", lambda: self.client.request("GET", "/api/suite/entorno"))
        self._execute("7.2", lambda: self.client.request("POST", "/api/suite/conexion", common, timeout=300))
        self._execute("7.3", lambda: self.client.request("POST", "/api/suite/validar_entradas", common, timeout=300))
        if self.allow_optimization:
            self._execute("7.4", lambda: self.client.request("POST", "/api/suite/pipeline", common, timeout=1800), write=True)
        else:
            self.evidence.append("7.4", "pending_real", "Optimizacion omitida; requiere --allow-optimization")
        self._execute("6.3", lambda: self.client.request("POST", "/api/informe/armar", dict(
            common, fill=True, ensure_lf=False, force_captures=False,
            require_delivery=True, run_evidence_path=self.evidence.events_path,
        ), timeout=1200), write=True)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Ruta universal RECYM 1..7")
    parser.add_argument("--mdb", required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--feeder", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:5055")
    parser.add_argument("--api-key", default=os.environ.get("RECYM_API_KEY"))
    parser.add_argument("--run-id")
    parser.add_argument("--resume-run")
    parser.add_argument("--out", default=os.path.join(ROOT, "data", "output", "runs"))
    parser.add_argument("--stage4-json", help="JSON con rows[] reales para cargas nuevas")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--allow-optimization", action="store_true")
    args = parser.parse_args(argv)
    if args.allow_optimization and not args.allow_write:
        parser.error("--allow-optimization requiere --allow-write")
    return args


def main(argv=None):
    args = parse_args(argv)
    identity = build_context_identity({
        "database_mdb": args.mdb,
        "study_path": args.study,
        "feeder_id": args.feeder,
        "network_id": args.network,
    }, require_complete=True)
    identity["context_fingerprint"] = context_fingerprint(identity)
    run_id = args.resume_run or args.run_id or uuid.uuid4().hex
    run_dir = os.path.join(os.path.realpath(args.out), run_id)
    evidence = RunEvidence(run_dir, run_id, identity, resume=bool(args.resume_run))
    client = ApiClient(args.base_url, identity, api_key=args.api_key)
    stage4 = _load_json(args.stage4_json)
    rows = stage4.get("rows") if isinstance(stage4, dict) else stage4
    try:
        UniversalRunner(
            client, evidence, allow_write=args.allow_write,
            allow_optimization=args.allow_optimization, stage4_rows=rows,
        ).run()
        result = evidence.finalize()
        print("Evidencia:", evidence.manifest_path)
        return 0 if result.get("ok") else 2
    except Exception as ex:
        print("STOP:", ex)
        evidence.finalize()
        print("Evidencia:", evidence.manifest_path)
        return 2


if __name__ == "__main__":
    sys.exit(main())
