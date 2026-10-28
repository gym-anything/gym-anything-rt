import {loadPyodide} from "https://cdn.jsdelivr.net/pyodide/v314.0.2/full/pyodide.mjs";

"use strict";

const PYODIDE_VERSION = "314.0.2";
const PYODIDE_BASE = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
let pyodidePromise = null;
let loadedGraderUrl = "";
let gradeJson = null;

function loadPython() {
  if (!pyodidePromise) {
    pyodidePromise = loadPyodide({indexURL: PYODIDE_BASE});
  }
  return pyodidePromise;
}

async function loadGrader(graderUrl) {
  if (gradeJson && loadedGraderUrl === graderUrl) return gradeJson;
  const [pyodide, sourceResponse] = await Promise.all([loadPython(), fetch(graderUrl)]);
  if (!sourceResponse.ok) throw new Error(`grader source unavailable (${sourceResponse.status})`);
  const source = await sourceResponse.text();
  pyodide.globals.set("browser_grader_source", source);
  pyodide.runPython(`
import json
import types

_browser_grader_module = types.ModuleType("gym_anything_rt_browser_grader")
exec(browser_grader_source, _browser_grader_module.__dict__)

def _gym_anything_rt_grade_json(payload_json, truth_json, state_json, context_json):
    payload = json.loads(payload_json)
    truth = json.loads(truth_json)
    state = json.loads(state_json)
    context = json.loads(context_json) if context_json else None
    if getattr(_browser_grader_module, "ACCEPTS_BROWSER_RUNTIME_CONTEXT", False):
        grade = _browser_grader_module.grade(
            payload,
            truth,
            state,
            runtime_context=context,
        )
    else:
        grade = _browser_grader_module.grade(payload, truth, state)
    if not isinstance(grade, dict):
        grade = {"graded": True, "passed": False, "feedback": "invalid grader result"}
    grade.setdefault("graded", True)
    grade.setdefault("passed", False)
    return json.dumps(grade, separators=(",", ":"))
`);
  gradeJson?.destroy?.();
  gradeJson = pyodide.globals.get("_gym_anything_rt_grade_json");
  loadedGraderUrl = graderUrl;
  return gradeJson;
}

self.addEventListener("message", async (event) => {
  const {id, graderUrl, payload, groundTruth, publicState, runtimeContext} = event.data || {};
  try {
    const grader = await loadGrader(graderUrl);
    const raw = grader(
      JSON.stringify(payload),
      JSON.stringify(groundTruth),
      JSON.stringify(publicState),
      runtimeContext ? JSON.stringify(runtimeContext) : "",
    );
    self.postMessage({id, ok: true, grade: JSON.parse(raw)});
  } catch (error) {
    self.postMessage({id, ok: false, error: error?.stack || error?.message || String(error)});
  }
});
