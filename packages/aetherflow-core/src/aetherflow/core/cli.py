import argparse
import json
import sys

from aetherflow.core.runner import run_flow
from aetherflow.core.bundles import bundle_status, sync_bundle
from aetherflow.core.validation import validate_flow_yaml
from aetherflow.core.diagnostics import doctor_check_env, explain_profiles_env


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    parser = argparse.ArgumentParser(prog="aetherflow", description="aetherflow-core CLI")
    sp = parser.add_subparsers(dest="cmd", required=True)

    bundlep = sp.add_parser("bundle", help="Bundle operations (sync remote bundles)")
    bsp = bundlep.add_subparsers(dest="bundle_cmd", required=True)

    syncp = bsp.add_parser("sync", help="Sync a bundle manifest into the local active directory")
    syncp.add_argument("--bundle-manifest", required=True, help="Path to bundle manifest YAML")
    syncp.add_argument("--work-root", default=None, help="Override work root (defaults to AETHERFLOW_WORK_ROOT or settings)")
    syncp.add_argument("--allow-stale-bundle", action="store_true", help="If sync fails, keep using last active bundle if present")
    syncp.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    syncp.add_argument("--print-local-root", action="store_true", help="Print the synced local root directory path")

    statp = bsp.add_parser("status", help="Show local bundle status (no remote fetch)")
    statp.add_argument("--bundle-manifest", required=True, help="Path to bundle manifest YAML")
    statp.add_argument("--work-root", default=None, help="Override work root (defaults to AETHERFLOW_WORK_ROOT or settings)")
    statp.add_argument("--json", action="store_true", help="Output machine-readable JSON")


    runp = sp.add_parser("run", help="Run a flow YAML once")
    runp.add_argument("--flow-yaml", help="Path to flow YAML")
    runp.add_argument("--run-id", default=None)
    runp.add_argument("--flow-job", default=None)
    runp.add_argument("--bundle-manifest", default=None, help="Optional bundle manifest (sync remote assets before run)")
    runp.add_argument("--allow-stale-bundle", action="store_true", help="If bundle sync fails, run with last active bundle")

    valp = sp.add_parser("validate", help="Validate a flow YAML (schema + semantic)")
    valp.add_argument("--flow-yaml", help="Path to flow YAML")
    valp.add_argument("--bundle-manifest", default=None, help="Optional bundle manifest (sync before validation)")
    valp.add_argument("--allow-stale-bundle", action="store_true")
    valp.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    docp = sp.add_parser("doctor", help="Doctor checks (env/profile sanity)")
    docp.add_argument("--flow-yaml", help="Path to flow YAML")
    docp.add_argument("--bundle-manifest", default=None, help="Optional bundle manifest (sync before checks)")
    docp.add_argument("--allow-stale-bundle", action="store_true")
    docp.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    explp = sp.add_parser("explain", help="Explain profile->env mappings (attribution + decode)")
    explp.add_argument("--flow-yaml", help="Path to flow YAML")
    explp.add_argument("--bundle-manifest", default=None)
    explp.add_argument("--allow-stale-bundle", action="store_true")
    explp.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args(argv)
    if args.cmd == "bundle":
        if args.bundle_cmd == "sync":
            res = sync_bundle(
                bundle_manifest=args.bundle_manifest,
                work_root=args.work_root,
                allow_stale=bool(args.allow_stale_bundle),
            )
            out = {
                "bundle_manifest": args.bundle_manifest,
                "local_root": str(res.local_root),
                "active_dir": str(res.active_dir),
                "cache_dir": str(res.cache_dir),
                "fingerprints_dir": str(res.fingerprints_dir),
                "fingerprint": res.fingerprint,
                "changed": bool(res.changed),
                "fetched_files": list(res.fetched_files),
            }
            if args.json:
                print(json.dumps(out, ensure_ascii=False))
            else:
                status = "CHANGED" if res.changed else "UNCHANGED"
                print(f"{status}: bundle synced to {res.local_root} fingerprint={res.fingerprint}")
                if args.print_local_root:
                    print(str(res.local_root))
            return 0

        if args.bundle_cmd == "status":
            st = bundle_status(bundle_manifest=args.bundle_manifest, work_root=args.work_root)
            out = {
                "bundle_manifest": args.bundle_manifest,
                "bundle_id": st.bundle_id,
                "work_root": str(st.work_root),
                "bundle_root": str(st.bundle_root),
                "active_dir": str(st.active_dir),
                "cache_dir": str(st.cache_dir),
                "fingerprints_dir": str(st.fingerprints_dir),
                "fingerprint": st.fingerprint,
                "has_active": bool(st.has_active),
            }
            if args.json:
                print(json.dumps(out, ensure_ascii=False))
            else:
                fp = st.fingerprint or "(none)"
                active = "yes" if st.has_active else "no"
                print(f"bundle_id={st.bundle_id} fingerprint={fp} has_active={active}")
                print(f"active_dir={st.active_dir}")
                print(f"cache_dir={st.cache_dir}")
                print(f"fingerprints_dir={st.fingerprints_dir}")
            return 0



    if args.cmd == "run":
        run_flow(
            args.flow_yaml,
            run_id=args.run_id,
            flow_job=args.flow_job,
            bundle_manifest=args.bundle_manifest,
            allow_stale_bundle=bool(args.allow_stale_bundle),
        )
        return 0

    if args.cmd == "validate":
        report = validate_flow_yaml(
            args.flow_yaml,
            bundle_manifest=args.bundle_manifest,
            allow_stale_bundle=bool(args.allow_stale_bundle),
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False))
        else:
            if report.get("ok"):
                print(f"OK: {report.get('flow_yaml')}")
            else:
                print(f"INVALID: {report.get('flow_yaml')}")
                for e in report.get("errors", []):
                    print(f"- {e.get('loc')}: {e.get('code')} - {e.get('msg')}")
            for w in report.get("warnings", []) or []:
                print(f"! {w.get('loc')}: {w.get('code')} - {w.get('msg')}")
        return 0 if report.get("ok") else 2

    if args.cmd == "doctor":
        report = doctor_check_env(
            args.flow_yaml,
            bundle_manifest=args.bundle_manifest,
            allow_stale_bundle=bool(args.allow_stale_bundle),
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False))
        else:
            if report.get("ok"):
                print(f"OK: {report.get('flow_yaml')}")
            else:
                print(f"FAIL: {report.get('flow_yaml')}")
                for it in report.get("missing_env", []):
                    print(
                        f"- resource={it.get('resource')} profile={it.get('profile')} {it.get('section')}.{it.get('field')} needs env {it.get('env_key')}"
                    )
        for w in report.get('warnings', []) or []:
            print(f"! {w.get('loc')}: {w.get('code')} - {w.get('msg')}")
        return 0 if report.get("ok") else 2

    if args.cmd == "explain":
        report = explain_profiles_env(
            args.flow_yaml,
            bundle_manifest=args.bundle_manifest,
            allow_stale_bundle=bool(args.allow_stale_bundle),
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False))
        else:
            print(f"Flow: {report.get('flow_yaml')}")
            resources = report.get("resources") or {}
            for rname, r in resources.items():
                print(f"\nResource: {rname} ({r.get('kind')}/{r.get('driver')}) profile={r.get('profile')}")
                dec = r.get("decode") or {}
                if dec:
                    print("  decode:")
                    print(f"    {json.dumps(dec, ensure_ascii=False)}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
