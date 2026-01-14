# rag_project_menu.py
import os
from pathlib import Path
from datetime import datetime
from utils import (
    ensure_dirs, find_files, read_text_from_file, compute_file_hash,
    load_metadata_db, save_metadata_db, register_contract_entry,
    detect_clause_changes, generate_updates_pdf, apply_amendment_file,
    save_text_as_pdf_or_txt, CONTRACTS_DIR, UPDATES_DIR
)
from regulatory_engine import RegulatoryEngine

# Optional LLM imports guarded (not required)
try:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_groq import ChatGroq
    from langchain.chains.combine_documents import create_stuff_documents_chain
    from langchain.chains import create_retrieval_chain
    LLM_AVAILABLE = True
except Exception:
    LLM_AVAILABLE = False

METADATA_DB = Path("metadata_db.json")

def extract_first_date(text):
    import re
    if not text:
        return None
    m = re.search(r"(19|20)\d{2}", text)
    if m:
        return m.group(0)
    return None

def scan_and_detect_changes():
    ensure_dirs()
    metadata = load_metadata_db()
    files = find_files(CONTRACTS_DIR)
    if not files:
        print("No contract files found in", CONTRACTS_DIR)
        return
    generated = []
    for p in files:
        cid = p.stem
        text = read_text_from_file(p) or ""
        file_hash = compute_file_hash(p)
        entry = metadata.get(cid)
        if not entry:
            # register new
            metadata = register_contract_entry(metadata, str(p), extract_first_date(text), file_hash or "", status="Active")
            metadata[cid]["last_updated"] = datetime.utcnow().isoformat()
            metadata[cid]["snapshot_text"] = text[:4000]
            print(f"[new] {cid} registered.")
            continue
        if entry.get("hash") == file_hash:
            continue
        # change detected
        print("Change detected:", cid)
        old_fp = Path(entry.get("file_path", "")) if entry.get("file_path") else None
        old_text = ""
        if old_fp and old_fp.exists():
            old_text = read_text_from_file(old_fp) or ""
        else:
            old_text = entry.get("snapshot_text", "") or ""
        changes = detect_clause_changes(old_text, text)
        out_name = f"Updated_{cid}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
        out_path = Path("updates") / out_name
        generate_updates_pdf(changes, out_path, cid, p.name)
        generated.append(str(out_path))
        # archive old file if exists
        if old_fp and old_fp.exists():
            # simple move/rename into archive
            from shutil import move
            ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            arch_name = f"{old_fp.name}.bak_{ts}"
            arch_path = Path("archive") / arch_name
            move(str(old_fp), str(arch_path))
            entry.setdefault("archived_paths", []).append(str(arch_path))
        # update metadata
        entry["hash"] = file_hash
        entry["file_path"] = str(p)
        entry["last_updated"] = datetime.utcnow().isoformat()
        entry["version"] = entry.get("version", 1) + 1
        entry["snapshot_text"] = text[:4000]
        entry["latest_update_pdf"] = str(out_path)
        metadata[cid] = entry

    save_metadata_db(metadata)
    print("Scan complete. Metadata saved.")
    for g in generated:
        print(" -", g)

def list_contracts():
    md = load_metadata_db()
    if not md:
        print("No metadata entries.")
        return
    print("\nContracts:")
    for cid, info in md.items():
        print(f"- {cid} | version: {info.get('version')} | status: {info.get('status')} | file: {info.get('file_path')}")
        print(f"    regulatory_status: {info.get('regulatory_status', 'N/A')} | age_status: {info.get('age_status', 'N/A')}")

def generate_before_after_and_diff():
    md = load_metadata_db()
    cid = input("Enter contract id (filename stem): ").strip()
    if cid not in md:
        print("Contract id not in metadata. Run a scan first.")
        return
    info = md[cid]
    cur_fp = Path(info.get("file_path", ""))
    cur_text = read_text_from_file(cur_fp) if cur_fp.exists() else info.get("snapshot_text", "")
    prev_text = ""
    archived = info.get("archived_paths", []) or []
    if archived:
        prev_fp = Path(archived[-1])
        if prev_fp.exists():
            prev_text = read_text_from_file(prev_fp)
    # fallback
    if not prev_text:
        prev_text = info.get("snapshot_text", "")

    out_dir = Path("pdf_outputs")
    out_dir.mkdir(parents=True, exist_ok=True)
    tstamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    before_path = out_dir / f"{cid}_before_{tstamp}.pdf"
    after_path = out_dir / f"{cid}_after_{tstamp}.pdf"
    diff_path = out_dir / f"{cid}_diff_{tstamp}.pdf"
    save_text_as_pdf_or_txt(prev_text or "(no previous)", before_path)
    save_text_as_pdf_or_txt(cur_text or "(no current)", after_path)
    changes = detect_clause_changes(prev_text or "", cur_text or "")
    diff_lines = ["Contract: " + cid, "", "ADDED:"] + ["+ " + a for a in changes.get("added", [])] + ["", "REMOVED:"] + ["- " + r for r in changes.get("removed", [])]
    save_text_as_pdf_or_txt("\n".join(diff_lines), diff_path)
    print("Before saved to:", before_path)
    print("After saved to: ", after_path)
    print("Diff saved to:  ", diff_path)

def run_regulatory_engine():
    ensure_dirs()
    md = load_metadata_db()
    engine = RegulatoryEngine()
    updated = engine.run_full_cycle(md)
    save_metadata_db(updated)
    print("Regulatory engine run complete. Check reg_updates/ for suggestions and metadata_db.json updated.")

def apply_proposal():
    md = load_metadata_db()
    cid = input("Enter contract id to apply amendment to: ").strip()
    if cid not in md:
        print("Not found in metadata.")
        return
    proposals = md[cid].get("regulatory_proposals", [])
    if not proposals:
        print("No proposals found for this contract.")
        return
    print("Proposals:")
    for i, p in enumerate(proposals, start=1):
        print(f"{i}) reg: {p.get('reg_id')} | risk: {p.get('risk')} | status: {p.get('status')}")
        print(f"    amendment txt: {p.get('amendment_txt')}")
    sel = input("Enter proposal number to apply (or 'q' to cancel): ").strip()
    if sel.lower() == "q":
        return
    try:
        n = int(sel) - 1
        p = proposals[n]
    except Exception:
        print("Invalid selection.")
        return
    txt_path = p.get("amendment_txt")
    if not txt_path or not Path(txt_path).exists():
        print("Amendment text file missing:", txt_path)
        return
    amendment_text = Path(txt_path).read_text(encoding="utf-8")
    # apply amendment
    try:
        apply_result = apply_amendment_file(md[cid]["file_path"], amendment_text, md)
        # update metadata
        md[cid]["file_path"] = apply_result["new_file"]
        md[cid]["version"] = apply_result["version"]
        md[cid].setdefault("applied_amendments", []).append({
            "reg_id": p.get("reg_id"),
            "applied_at": datetime.utcnow().isoformat(),
            "details": apply_result
        })
        # mark proposal as applied
        proposals[n]["status"] = "applied"
        save_metadata_db(md)
        print("Amendment applied, new file:", apply_result["new_file"])
    except Exception as e:
        print("Error applying amendment:", e)

def main_menu():
    ensure_dirs()
    while True:
        print("\n==== Regulatory Update Tracker ====")
        print("1) Scan Contracts (detect changes & create update PDFs)")
        print("2) List Contracts & Metadata")
        print("3) Generate Before/After/Diff PDFs for a contract")
        print("4) Run Regulatory Engine (generate amendment suggestions)")
        print("5) Apply a Proposal to a Contract")
        print("6) Exit")
        choice = input("Choose [1-6]: ").strip()
        if choice == "1":
            scan_and_detect_changes()
        elif choice == "2":
            list_contracts()
        elif choice == "3":
            generate_before_after_and_diff()
        elif choice == "4":
            run_regulatory_engine()
        elif choice == "5":
            apply_proposal()
        elif choice == "6":
            print("Bye.")
            break
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main_menu()
