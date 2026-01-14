# regulatory_engine.py
import json
from pathlib import Path
from datetime import datetime
from utils import read_text_from_file, ensure_dirs, save_metadata_db, REG_UPDATES_DIR, METADATA_DB, register_contract_entry, apply_amendment_file, save_text_as_pdf_or_txt

# local config
REG_DB_FILE = Path("regulatory_db.json")
REG_UPDATES_DIR = Path("reg_updates")
DEMO_REGS = [
    {
        "id": "reg-2025-gdpr-consent",
        "title": "GDPR: Consent Recordkeeping Update",
        "jurisdiction": "EU",
        "date_published": "2025-10-01",
        "summary": "Requires explicit recording of consent metadata including timestamp and purpose.",
        "keywords": ["consent", "personal data", "gdpr", "recordkeeping"]
    },
    {
        "id": "reg-2025-data-localisation",
        "title": "Data Localisation Advisory",
        "jurisdiction": "IN",
        "date_published": "2025-09-15",
        "summary": "Advisory recommending storage of certain personal data within jurisdictional borders.",
        "keywords": ["localis", "data localisation", "personal data", "cross-border"]
    }
]

def ensure_reg_db():
    if not REG_DB_FILE.exists():
        REG_DB_FILE.write_text(json.dumps(DEMO_REGS, indent=2, ensure_ascii=False), encoding="utf-8")

class RegulatoryEngine:
    def __init__(self, updates_dir: Path = REG_UPDATES_DIR):
        ensure_dirs()
        ensure_reg_db()
        self.updates_dir = updates_dir
        self.updates_dir.mkdir(parents=True, exist_ok=True)
        # load regs into memory
        self.regs = self.load_reg_db()

    def load_reg_db(self):
        try:
            return json.loads(REG_DB_FILE.read_text(encoding="utf-8"))
        except Exception:
            return DEMO_REGS

    def save_reg_db(self, regs):
        REG_DB_FILE.write_text(json.dumps(regs, indent=2, ensure_ascii=False), encoding="utf-8")

    def fetch_regulatory_updates(self):
        # demo: return regs (in real system add API callers)
        regs = self.load_reg_db()
        return regs

    def _keyword_score(self, reg_keywords, text):
        if not text:
            return 0
        t = text.lower()
        hits = 0
        for kw in reg_keywords:
            if kw.lower() in t:
                hits += 1
        if not reg_keywords:
            return 0
        return int((hits / len(reg_keywords)) * 100)

    def _jurisdiction_boost(self, reg_jur, contract_jur):
        if not reg_jur:
            return 0
        r = (reg_jur or "").lower()
        c = (contract_jur or "").lower()
        if r == "global":
            return 10
        if r == c:
            return 30
        return 0

    def compute_risk(self, reg, contract_meta, contract_text):
        kw_score = self._keyword_score(reg.get("keywords", []), contract_text)
        jur_boost = self._jurisdiction_boost(reg.get("jurisdiction", ""), contract_meta.get("jurisdiction", ""))
        # age penalty (minor)
        age_penalty = 0
        last_up = contract_meta.get("last_updated") or contract_meta.get("date")
        if last_up:
            try:
                yr = int(str(last_up)[:4])
                age = max(0, datetime.now().year - yr)
                if age > 3:
                    age_penalty = min(10, (age - 3) * 2)
            except Exception:
                age_penalty = 0
        raw = kw_score + jur_boost + age_penalty
        return min(100, int(raw))

    def generate_amendment_text(self, reg, matches, contract_meta):
        lines = []
        lines.append(f"Amendment suggestion for {reg.get('id')}: {reg.get('title')}")
        lines.append(f"Jurisdiction: {reg.get('jurisdiction')} | Published: {reg.get('date_published')}")
        lines.append("")
        lines.append("Summary:")
        lines.append(reg.get("summary", ""))
        lines.append("")
        lines.append("Detected matches:")
        lines.append(", ".join(matches) if matches else "None")
        lines.append("")
        lines.append("Suggested (draft) clause language:")
        # templated examples
        if any("consent" in (m or "").lower() for m in matches):
            lines.append("- Consent recordkeeping: The parties shall obtain explicit consent and retain timestamp and purpose of consent for audit purposes.")
        if any("localis" in (m or "").lower() or "local" in (m or "").lower() for m in matches):
            lines.append("- Data localisation: Certain personal data must be stored within the jurisdiction and transferred only under documented safeguards.")
        if any("privacy" in (m or "").lower() or "notice" in (m or "").lower() for m in matches):
            lines.append("- Privacy notice: Update privacy notice to include profiling logic and legal basis for processing.")
        if not matches:
            lines.append("- General recommendation: review contract for personal data handling and add explicit responsibilities.")
        lines.append("")
        lines.append(f"Generated by RegulatoryEngine at {datetime.utcnow().isoformat()} UTC")
        return "\n".join(lines)

    def save_amendment(self, contract_id: str, reg: dict, amendment_text: str):
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        base = f"{contract_id}__{reg.get('id')}__{ts}"
        txt_path = self.updates_dir / f"{base}.txt"
        pdf_path = self.updates_dir / f"{base}.pdf"
        txt_path.write_text(amendment_text, encoding="utf-8")
        save_text_as_pdf_or_txt(amendment_text, pdf_path)
        return {"txt": str(txt_path), "pdf": str(pdf_path)}

    def run_full_cycle(self, metadata: dict, auto_apply_threshold: int = 90):
        """
        For every regulation and contract in metadata, compute risk and create amendment suggestions
        if risk >= 40 (default). If metadata[contract_id].get('auto_apply') is True and risk >= auto_apply_threshold,
        the amendment will be automatically applied (dangerous in prod — demo only).
        """
        regs = self.fetch_regulatory_updates()
        proposals = []
        for reg in regs:
            for cid, info in list(metadata.items()):
                if "Archived" in info.get("status", ""):
                    continue
                fp = info.get("file_path")
                if not fp:
                    continue
                text = read_text_from_file(Path(fp)) or ""
                # find keyword matches
                kw_matches = []
                for kw in reg.get("keywords", []):
                    if kw.lower() in (text or "").lower():
                        kw_matches.append(kw)
                risk = self.compute_risk(reg, info, text)
                # threshold for suggestion (configurable) - here we pick >=40
                if risk >= 40:
                    amendment = self.generate_amendment_text(reg, kw_matches, info)
                    saved = self.save_amendment(cid, reg, amendment)
                    prop = {
                        "contract_id": cid,
                        "reg_id": reg.get("id"),
                        "risk": risk,
                        "matches": kw_matches,
                        "amendment_txt": saved.get("txt"),
                        "amendment_pdf": saved.get("pdf"),
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    proposals.append(prop)
                    # attach proposal to metadata
                    prop_meta = info.get("regulatory_proposals", [])
                    prop_meta.append({**prop, "status": "suggested"})
                    info["regulatory_proposals"] = prop_meta
                    # simple regulatory_status label
                    if risk >= 75:
                        info["regulatory_status"] = "High Risk"
                    elif risk >= 50:
                        info["regulatory_status"] = "Needs Update"
                    else:
                        info["regulatory_status"] = "Monitor"

                    # Auto-apply if contract metadata says so AND very high risk
                    if info.get("auto_apply") and risk >= auto_apply_threshold:
                        try:
                            apply_result = apply_amendment_file(info["file_path"], amendment, metadata)
                            # update metadata with applied info
                            info["file_path"] = apply_result["new_file"]
                            info["version"] = apply_result["version"]
                            info.setdefault("applied_amendments", []).append({
                                "reg_id": reg.get("id"),
                                "applied_at": datetime.utcnow().isoformat(),
                                "details": apply_result
                            })
                        except Exception as e:
                            info.setdefault("apply_errors", []).append(str(e))
                else:
                    # keep/mark OK
                    info["regulatory_status"] = info.get("regulatory_status", "OK")
                # update age_status info
                last_up = info.get("last_updated") or info.get("date")
                if last_up:
                    try:
                        yr = int(str(last_up)[:4])
                        age = max(0, datetime.now().year - yr)
                        if age <= 1:
                            info["age_status"] = "Up to 1 year"
                        elif age <= 3:
                            info["age_status"] = "1-3 years"
                        elif age <= 6:
                            info["age_status"] = "3-6 years"
                        else:
                            info["age_status"] = "6+ years"
                    except Exception:
                        info["age_status"] = "Unknown"
                metadata[cid] = info

        # persist a proposals log for visibility
        proposals_log = self.updates_dir / f"proposals_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json"
        proposals_log.write_text(json.dumps(proposals, indent=2, ensure_ascii=False), encoding="utf-8")
        # return updated metadata (caller should save)
        return metadata
