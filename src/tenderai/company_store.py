"""Per-company DB-backed settings store. One row per (company_id, section) in company_settings."""


from sqlalchemy.orm import Session

from .models import AppSettings, CompanySettings

MUTABLE_SECTIONS = frozenset({"classification", "scheduler", "email"})


class CompanyStore:
    @staticmethod
    def get_section(db: Session, company_id: int, section: str) -> dict | None:
        row = (
            db.query(CompanySettings)
            .filter(
                CompanySettings.company_id == company_id,
                CompanySettings.section == section,
            )
            .first()
        )
        return row.data if row else None

    @staticmethod
    def put_section(
        db: Session,
        company_id: int,
        section: str,
        data: dict,
        updated_by: str = "system",
    ) -> None:
        row = CompanySettings(
            company_id=company_id, section=section, data=data, updated_by=updated_by
        )
        db.merge(row)
        db.commit()

    @staticmethod
    def get_all(db: Session, company_id: int) -> dict[str, dict]:
        rows = (
            db.query(CompanySettings)
            .filter(CompanySettings.company_id == company_id)
            .all()
        )
        return {row.section: row.data for row in rows}

    @staticmethod
    def get_all_with_fallback(db: Session, company_id: int) -> dict[str, dict]:
        """Return per-company settings, falling back to global AppSettings for missing sections."""
        global_rows = db.query(AppSettings).all()
        merged = {row.section: row.data for row in global_rows}
        company_rows = (
            db.query(CompanySettings)
            .filter(CompanySettings.company_id == company_id)
            .all()
        )
        for row in company_rows:
            merged[row.section] = row.data
        return merged

    @staticmethod
    def seed_from_global(db: Session, company_id: int) -> list[str]:
        """Copy AppSettings rows into CompanySettings for a new company. Idempotent."""
        global_rows = db.query(AppSettings).all()
        seeded: list[str] = []
        for row in global_rows:
            exists = (
                db.query(CompanySettings)
                .filter(
                    CompanySettings.company_id == company_id,
                    CompanySettings.section == row.section,
                )
                .first()
            )
            if not exists:
                db.add(
                    CompanySettings(
                        company_id=company_id,
                        section=row.section,
                        data=row.data,
                        updated_by="seed",
                    )
                )
                seeded.append(row.section)
        db.commit()
        return seeded
