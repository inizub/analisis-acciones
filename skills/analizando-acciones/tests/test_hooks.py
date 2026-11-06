import io
import json
from pathlib import Path

import pytest

import ejecucion
from artefactos import dp_completo, ejemplo, forense, sintesis
from hooks import guardia, validar_salida

RAIZ_PLUGIN = Path(__file__).resolve().parents[3]
REFERENCIAS = RAIZ_PLUGIN / "skills" / "analizando-acciones" / "references"


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(RAIZ_PLUGIN))
    r = ejecucion.iniciar("XYZ completo", tmp_path / "journal", "2026-11-06")
    return Path(r["run_dir"])


def evento(agente, tool, **ti):
    return {"agent_type": agente, "tool_name": tool, "tool_input": ti, "cwd": str(RAIZ_PLUGIN)}


def bloquea(ev):
    try:
        guardia.pre(ev)
    except SystemExit as e:
        return e.code == 2
    return False


AN = "analisis-acciones:analista-fundamental"


# ---------------------------------------------------------------- nombres y activación

def test_nombre_agente():
    assert guardia.nombre_agente("analisis-acciones:juez") == "juez"
    assert guardia.nombre_agente("juez") == "juez"
    assert guardia.nombre_agente("otro-plugin:juez") is None
    assert guardia.nombre_agente("Explore") is None and guardia.nombre_agente(None) is None


def test_sin_ejecucion_activa_o_sin_agente_no_bloquea(run):
    assert not bloquea({"tool_name": "WebFetch", "tool_input": {"url": "https://x"}})          # sesión principal
    assert not bloquea(evento("Explore", "WebFetch", url="https://x"))
    ejecucion.terminar()
    assert not bloquea(evento(AN, "WebFetch", url="https://x"))                                 # sin ejecución activa


# ---------------------------------------------------------------- red y Bash

@pytest.mark.parametrize("agente", [AN, "analisis-acciones:forense", "analisis-acciones:red-team"])
@pytest.mark.parametrize("tool", ["WebFetch", "WebSearch", "Bash", "mcp__claude_ai_Gmail__send_message"])
def test_agentes_aislados_sin_red_ni_bash(run, agente, tool):
    assert bloquea(evento(agente, tool, command="curl https://x", url="https://x"))


def test_el_agente_datos_si_tiene_red(run):
    assert not bloquea(evento("analisis-acciones:datos", "WebFetch", url="https://sec.gov"))
    assert not bloquea(evento("analisis-acciones:datos", "Bash", command="ls"))


@pytest.mark.parametrize("cmd,permitido", [
    ('bash "C:/plug/skills/analizando-acciones/scripts/py.sh" "C:/data" motor/escenarios.py --analista a.json --motor m.json', True),
    ('bash /p/skills/analizando-acciones/scripts/py.sh /d agregar.py --dir /run --modo completo', True),
    ('bash /p/skills/analizando-acciones/scripts/py.sh /d gate.py --dir /run --modo completo', True),
    ('bash /p/skills/analizando-acciones/scripts/py.sh /d motor/escenarios.py --analista a.json; rm -rf /', False),
    ('bash /p/skills/analizando-acciones/scripts/py.sh /d diario.py cerrar --dir /run', False),
    ('curl https://example.com', False),
    ('bash /p/skills/analizando-acciones/scripts/py.sh /d agregar.py $(cat /etc/passwd)', False)])
def test_bash_del_juez(run, cmd, permitido):
    assert bloquea(evento("analisis-acciones:juez", "Bash", command=cmd)) is not permitido


def test_juez_sin_red(run):
    assert bloquea(evento("analisis-acciones:juez", "WebSearch", query="x"))


# ---------------------------------------------------------------- lectura

def test_analista_lee_solo_la_ejecucion_y_references(run):
    assert not bloquea(evento(AN, "Read", file_path=str(run / "datapack.json")))
    assert not bloquea(evento(AN, "Read", file_path=str(run / "motor_inicial.json")))
    assert not bloquea(evento(AN, "Read", file_path=str(REFERENCIAS / "metodologia.md")))
    assert bloquea(evento(AN, "Read", file_path=str(RAIZ_PLUGIN / "SPEC.md")))
    assert bloquea(evento(AN, "Read", file_path=str(run.parent / "2026-10-01" / "verdict.json")))
    assert bloquea(evento(AN, "Glob", pattern="**/*.json"))                                   # sin path: cwd fuera


@pytest.mark.parametrize("archivo", ["analista_B.json", "analista_A.json", "escenarios_A.json", "objeciones.json",
                                     "juez.json", "forense.json", "agregado.json", "verdict.json"])
def test_fase_ciega_analista_no_lee_salidas_ajenas(run, archivo):
    assert bloquea(evento(AN, "Read", file_path=str(run / archivo)))


def test_grep_sobre_directorio_bloqueado_en_fase_ciega(run):
    (run / "datapack.json").write_text("{}", encoding="utf-8")
    assert bloquea(evento(AN, "Grep", pattern="p", path=str(run)))
    assert not bloquea(evento(AN, "Grep", pattern="ingresos", path=str(run / "datapack.json")))
    assert bloquea(evento(AN, "Grep", pattern="p", path=str(run / "analista_B.json")))
    assert not bloquea(evento(AN, "Glob", pattern="*.json", path=str(run)))                    # Glob solo lista nombres


def test_red_team_lee_los_informes_congelados_pero_no_al_juez(run):
    rt = "analisis-acciones:red-team"
    assert not bloquea(evento(rt, "Read", file_path=str(run / "analista_A.json")))
    assert not bloquea(evento(rt, "Read", file_path=str(run / "escenarios_B.json")))
    assert bloquea(evento(rt, "Read", file_path=str(run / "juez.json")))
    assert bloquea(evento(rt, "Read", file_path=str(run / "ajustes.json")))


def test_juez_lee_todo_dentro_de_la_ejecucion(run):
    j = "analisis-acciones:juez"
    for f in ("analista_A.json", "objeciones.json", "escenarios_B.json"):
        assert not bloquea(evento(j, "Read", file_path=str(run / f)))
    assert bloquea(evento(j, "Read", file_path="C:/Users/otro/secreto.txt"))


def test_forense_no_lee_a_los_analistas(run):
    f = "analisis-acciones:forense"
    assert not bloquea(evento(f, "Read", file_path=str(run / "forense_metricas.json")))
    assert bloquea(evento(f, "Read", file_path=str(run / "analista_A.json")))


# ---------------------------------------------------------------- escritura

@pytest.mark.parametrize("agente,archivo,permitido", [
    (AN, "analista_A.json", True), (AN, "analista_B1.json", True), (AN, "confirmacion_ruta.json", True),
    (AN, "datapack.json", False), (AN, "juez.json", False),
    ("analisis-acciones:datos", "datos_agente.json", True), ("analisis-acciones:datos", "datapack.json", False),
    ("analisis-acciones:forense", "forense.json", True), ("analisis-acciones:forense", "forense_metricas.json", False),
    ("analisis-acciones:red-team", "objeciones.json", True), ("analisis-acciones:juez", "juez.json", True),
    ("analisis-acciones:juez", "ajustes.json", True), ("analisis-acciones:juez", "analista_A.json", False)])
def test_cada_agente_escribe_solo_lo_suyo(run, agente, archivo, permitido):
    assert bloquea(evento(agente, "Write", file_path=str(run / archivo), content="{}")) is not permitido


def test_escritura_fuera_de_la_ejecucion(run):
    assert bloquea(evento(AN, "Write", file_path=str(run.parent / "analista_A.json"), content="{}"))
    assert bloquea(evento("analisis-acciones:datos", "Edit", file_path=str(RAIZ_PLUGIN / "README.md")))


# ---------------------------------------------------------------- traza

def test_post_escribe_la_traza(run):
    guardia.post(evento(AN, "Read", file_path=str(run / "datapack.json")))
    guardia.post({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
    lineas = [json.loads(l) for l in (run / "traza.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lineas[0]["agent_type"] == AN and lineas[0]["args_resumidos"]["file_path"].endswith("datapack.json")
    assert lineas[1]["agent_type"] == "principal" and lineas[1]["args_resumidos"] == {"command": "ls -la"}


def test_main_lee_stdin(run, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(evento(AN, "WebFetch", url="https://x"))))
    monkeypatch.setattr("sys.argv", ["guardia.py", "pre"])
    with pytest.raises(SystemExit) as e:
        guardia.main()
    assert e.value.code == 2
    monkeypatch.setattr("sys.stdin", io.StringIO("no es json"))
    assert guardia.main() == 0


# ---------------------------------------------------------------- SubagentStop

def stop(monkeypatch, agente, mensaje="", agent_id="ag1"):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"agent_type": agente, "agent_id": agent_id, "last_assistant_message": mensaje})))
    return validar_salida.main()


def test_validar_salida_analista(run, monkeypatch):
    assert stop(monkeypatch, AN, "Escrito en analista_A.json") == 2           # no existe todavía
    (run / "analista_A.json").write_text(json.dumps(ejemplo("analista_A.json")), encoding="utf-8")
    assert stop(monkeypatch, AN, "Escrito en analista_A.json") == 0
    malo = ejemplo("analista_A.json")
    malo["escenarios"][0]["p"] = 0.5
    (run / "analista_B.json").write_text(json.dumps(malo), encoding="utf-8")
    assert stop(monkeypatch, AN, "Escrito en analista_B.json", "ag2") == 2
    assert stop(monkeypatch, AN, "Escrito en analista_A.json", "ag3") == 0     # valida el suyo, no el de B


def test_validar_salida_no_entra_en_bucle(run, monkeypatch):
    for i in range(3):
        assert stop(monkeypatch, "analisis-acciones:red-team", "", "rt") == 2
    assert stop(monkeypatch, "analisis-acciones:red-team", "", "rt") == 0      # cuarto intento: se deja terminar


def test_validar_salida_juez_forense_y_datos(run, monkeypatch):
    (run / "juez.json").write_text(json.dumps(sintesis()), encoding="utf-8")
    assert stop(monkeypatch, "analisis-acciones:juez") == 0
    (run / "ajustes.json").write_text(json.dumps({"ticker": "X", "fecha_analisis": "2026-11-06", "ajustes": [{}]}), encoding="utf-8")
    assert stop(monkeypatch, "analisis-acciones:juez", agent_id="j2") == 2
    (run / "forense.json").write_text(json.dumps(forense()), encoding="utf-8")
    assert stop(monkeypatch, "analisis-acciones:forense") == 0
    (run / "datapack_base.json").write_text(json.dumps(dp_completo()), encoding="utf-8")
    (run / "datos_agente.json").write_text(json.dumps({"banca": {"cet1": {"valor": 1}}}), encoding="utf-8")
    assert stop(monkeypatch, "analisis-acciones:datos", agent_id="d1") == 2
    (run / "datos_agente.json").write_text(json.dumps({"fuentes": []}), encoding="utf-8")
    assert stop(monkeypatch, "analisis-acciones:datos", agent_id="d2") == 0


def test_validar_salida_ignora_otros_agentes(run, monkeypatch):
    assert stop(monkeypatch, "Explore") == 0
    ejecucion.terminar()
    assert stop(monkeypatch, AN, "analista_A.json") == 0


def test_hooks_json_apunta_a_scripts_que_existen():
    h = json.loads((RAIZ_PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    for evento_ in ("PreToolUse", "PostToolUse", "SubagentStop"):
        for grupo in h["hooks"][evento_]:
            for hook in grupo["hooks"]:
                scripts = [a for a in hook["args"] if a.endswith(".py")]
                assert scripts
                for s in scripts:
                    assert (RAIZ_PLUGIN / s.replace("${CLAUDE_PLUGIN_ROOT}/", "")).exists(), s
