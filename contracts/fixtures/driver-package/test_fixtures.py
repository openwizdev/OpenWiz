import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]
CHECKOUT = CONTRACTS.parent
STAMP = "runtime/openwiz-build.txt"
PROBE = r"""
import importlib.machinery, importlib.util, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
KIT = os.path.join(ROOT, 'kernel', 'driver-kit')
def credential():
    spec = importlib.util.spec_from_loader('kit', importlib.machinery.SourceFileLoader('kit', os.path.join(KIT, 'kit.py')))
    kit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kit)
    return [kit.holds_credential('token=synthetic'), kit.holds_credential('build-ticket')]
def key_helper():
    asked = json.dumps({'host': 'synthetic-host', 'method': 'GET', 'path': '/'})
    p = subprocess.run([sys.executable, '-I', os.path.join(KIT, 'hostkey.py')], input=asked, capture_output=True, text=True)
    return json.loads(p.stdout)['error']
def skills_pin():
    with open(os.path.join(ROOT, 'wizskills.lock')) as f:
        return sorted(json.load(f))
def build_stamp():
    with open(os.path.join(ROOT, 'openwiz-build.txt')) as f:
        return f.readline()
print(json.dumps({f.__name__: f for f in (credential, key_helper, skills_pin, build_stamp)}[sys.argv[1]]()))
"""


def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate JSON key")
    return result


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def shape_errors(root, schema, value, path=""):
    allowed = {"$ref", "type", "const", "pattern", "maxLength", "required", "properties",
               "additionalProperties", "minItems", "maxItems", "items", "contains",
               "allOf", "oneOf"}
    if schema.keys() - allowed:
        raise ValueError("unsupported fixture schema keyword")
    if "$ref" in schema:
        prefix, name = schema["$ref"].rsplit("/", 1)
        if prefix != "#/$defs" or len(schema) != 1:
            raise ValueError("unsupported fixture schema reference")
        return shape_errors(root, root["$defs"][name], value, path)
    if "type" in schema:
        kind = {"array": list, "object": dict, "string": str}[schema["type"]]
        if type(value) is not kind:
            return [(path, "type")]
    failures = []
    def check(keyword, passes):
        if keyword in schema and not passes:
            failures.append((path, keyword))
    def nested(subschema, item, key=None):
        child_path = path if key is None else f"{path}/{key}".lstrip("/")
        return shape_errors(root, subschema, item, child_path)
    check("const", value == schema.get("const"))
    if isinstance(value, str):
        check("pattern", re.search(schema.get("pattern", ""), value) is not None)
        check("maxLength", len(value) <= schema.get("maxLength", len(value)))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        check("required", set(schema.get("required", ())) <= value.keys())
        check("additionalProperties", schema.get("additionalProperties") is not False
              or value.keys() <= properties.keys())
        for key in value.keys() & properties.keys():
            failures.extend(nested(properties[key], value[key], key))
    if isinstance(value, list):
        check("minItems", len(value) >= schema.get("minItems", 0))
        check("maxItems", len(value) <= schema.get("maxItems", len(value)))
        if "contains" in schema:
            check("contains", any(not nested(schema["contains"], item) for item in value))
        if "items" in schema:
            for i, item in enumerate(value):
                failures.extend(nested(schema["items"], item, i))
    if "oneOf" in schema:
        check("oneOf", sum(not nested(rule, value) for rule in schema["oneOf"]) == 1)
    for rule in schema.get("allOf", ()):
        failures.extend(nested(rule, value))
    return sorted(failures)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tar_members(data):
    raw = gzip.decompress(data)
    offset = 0
    while raw[offset:offset + 512] != bytes(512):
        member = tarfile.TarInfo.frombuf(raw[offset:offset + 512], "ascii", "strict")
        if raw[offset + 257:offset + 265] != b"ustar\x0000" or member.size < 0:
            raise ValueError("invalid USTAR header")
        offset += 512
        if offset + member.size > len(raw):
            raise ValueError("truncated tar member")
        yield member, raw[offset:offset + member.size]
        offset += ((member.size + 511) // 512) * 512
    if len(raw) - offset < 1024 or any(raw[offset:]):
        raise ValueError("invalid tar trailer")


def package_rules(package, manifest, archive, kit_schema):
    failures = set()
    release_url = (f"https://github.com/{package['repository']}/releases/download/"
                   f"v{package['version']}/driver.tar.gz")
    if package["asset_url"] != release_url:
        failures.add("asset-repository")
    if package["sha256"] != digest(archive):
        failures.add("archive-sha256")
    if manifest["driver"] != package["driver"]:
        failures.add("driver-name")
    if any(manifest[key] != package[key] for key in ("version", "kit_commit")):
        failures.add("release-identity")

    entries = {entry["path"]: entry for entry in manifest["files"]}
    if len(entries) != len(manifest["files"]):
        failures.add("duplicate-manifest-path")
    seen = set()
    for member, data in tar_members(archive):
        path = member.name
        if path in seen:
            failures.add("duplicate-member")
        seen.add(path)
        if path not in entries:
            failures.add("extra-file")
        if member.type != tarfile.REGTYPE:
            failures.add("member-type")
            continue
        if path in entries:
            if entries[path]["mode"] != f"{member.mode:04o}":
                failures.add("member-mode")
            if entries[path]["sha256"] != digest(data):
                failures.add("member-sha256")
        if path == "schema.json" and data != kit_schema:
            failures.add("kit-schema")
        if path == "README.md":
            lines = data.decode("utf-8").splitlines()
            names = [line for line in lines if line.startswith("Driver:")]
            if names != [f"Driver: {package['driver']}"]:
                failures.add("driver-name")
    if entries.keys() - seen:
        failures.add("missing-file")
    return failures


def kit_files():
    text = (CONTRACTS / "driver-package.v1.md").read_text(encoding="utf-8")
    section = text.partition("\n## Kit files\n")[2].partition("\n## ")[0]
    return re.findall(r"^\| `([^`]+)` \|", section, re.M)


def install_root(folder):
    build = folder / "build"
    (build / "runtime").mkdir(parents=True)
    (build / STAMP).write_text("openwiz.package.v1\n0.2.0\n")
    root = folder / "install"
    root.mkdir()
    for path in kit_files():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        source = build / "runtime" / path
        shutil.copyfile(source if source.exists() else CHECKOUT / path, target)
        target.chmod(0o600)
    return root


def add_driver(root, name, program):
    driver = root / "drivers" / name / "driver"
    driver.parent.mkdir(parents=True)
    driver.write_bytes(program)
    driver.chmod(0o700)
    return driver


def run(driver, *args, stdin=""):
    p = subprocess.run([sys.executable, "-I", str(driver), *args], input=stdin, capture_output=True,
                       text=True, timeout=60, env={"PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir()})
    return p.returncode, p.stdout


class DriverPackageFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = read_json(CONTRACTS / "driver-package.v1.schema.json")

    def errors(self, kind, value):
        ref = {"$ref": f"#/$defs/{kind}"} if "$defs" in self.schema else {}
        return shape_errors(self.schema, ref, value)

    def test_package_refusals_are_isolated(self):
        kit_schema = (CHECKOUT / "kernel/driver-kit/schema.json").read_bytes()
        cases = read_json(HERE / "cases.json")
        self.assertEqual(set(cases), {p.name for p in HERE.iterdir() if p.is_dir()})
        for case, refusal in cases.items():
            with self.subTest(case=case):
                folder = HERE / case
                package = read_json(folder / "package.json")
                manifest = read_json(folder / "manifest.json")
                archive = (folder / "driver.tar.gz").read_bytes()
                self.assertEqual([], self.errors("package", package))
                self.assertEqual([], self.errors("manifest", manifest))
                if self.schema:
                    for value in (package, manifest):
                        self.assertEqual([], shape_errors(self.schema, {"oneOf": self.schema["oneOf"]}, value))
                sums = "".join(f"{digest((folder / name).read_bytes())}  {name}\n"
                               for name in ("driver.tar.gz", "manifest.json"))
                self.assertEqual(sums, (folder / "SHA256SUMS").read_text())
                self.assertEqual({refusal} if refusal else set(),
                                 package_rules(package, manifest, archive, kit_schema))

    def test_record_shapes_accept_good_and_refuse_one_field(self):
        for kind in ("key_host", "pin", "approval"):
            with self.subTest(kind=kind):
                self.assertEqual([], self.errors(kind, read_json(HERE / f"{kind}.json")))
        for case in read_json(HERE / "shape-cases.json"):
            with self.subTest(kind=case["kind"], error=case["error"]):
                self.assertEqual([tuple(case["error"])], self.errors(case["kind"], case["value"]))

    def test_packaged_drivers_find_every_kit_file_they_use(self):
        with tempfile.TemporaryDirectory() as temp:
            root = install_root(Path(temp))
            probe = add_driver(root, "synthetic-host", PROBE.encode())
            expected = {"credential": [True, False],
                        "key_helper": "host is not in kernel/driver-kit/hosts.json",
                        "skills_pin": ["commit", "tree", "version"],
                        "build_stamp": "openwiz.package.v1\n"}
            for use, answer in expected.items():
                with self.subTest(use=use):
                    self.assertEqual((0, json.dumps(answer) + "\n"), run(probe, use))

    def test_todays_drivers_answer_as_they_do_in_the_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = install_root(Path(temp))
            for source in sorted(CHECKOUT.glob("adapters/*/driver")):
                name = source.parent.name
                driver = add_driver(root, name, source.read_bytes())
                with self.subTest(driver=name):
                    self.assertEqual(run(source, "start", stdin="{}"), run(driver, "start", stdin="{}"))

    def test_package_schema_is_checked_against_the_installed_kit(self):
        with tempfile.TemporaryDirectory() as temp:
            kit_schema = install_root(Path(temp)) / "kernel/driver-kit/schema.json"
            self.assertTrue(kit_schema.is_file(), "the install has no kit schema to check a package against")
            for case, refusals in (("good", set()), ("changed-schema", {"kit-schema"})):
                with self.subTest(case=case):
                    folder = HERE / case
                    self.assertEqual(refusals, package_rules(
                        read_json(folder / "package.json"), read_json(folder / "manifest.json"),
                        (folder / "driver.tar.gz").read_bytes(), kit_schema.read_bytes()))


if __name__ == "__main__":
    unittest.main()
