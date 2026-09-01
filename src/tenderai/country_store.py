"""Per-country DB-backed settings store. One row per (country_id, section) in country_settings."""


from sqlalchemy.orm import Session

from .models import AppSettings, CountrySettings

MUTABLE_SECTIONS = frozenset(
    {"pipeline", "scheduler", "llm", "email", "rag", "classification", "prompts"}
)


class CountryStore:
    @staticmethod
    def get_section(db: Session, country_id: int, section: str) -> dict | None:
        row = (
            db.query(CountrySettings)
            .filter(
                CountrySettings.country_id == country_id,
                CountrySettings.section == section,
            )
            .first()
        )
        return row.data if row else None

    @staticmethod
    def put_section(
        db: Session,
        country_id: int,
        section: str,
        data: dict,
        updated_by: str = "system",
    ) -> None:
        row = CountrySettings(
            country_id=country_id, section=section, data=data, updated_by=updated_by
        )
        db.merge(row)
        db.commit()

    @staticmethod
    def get_all(db: Session, country_id: int) -> dict[str, dict]:
        rows = (
            db.query(CountrySettings)
            .filter(CountrySettings.country_id == country_id)
            .all()
        )
        return {row.section: row.data for row in rows}

    @staticmethod
    def get_all_with_fallback(db: Session, country_id: int) -> dict[str, dict]:
        """Return per-country settings, falling back to global AppSettings for missing sections."""
        global_rows = db.query(AppSettings).all()
        merged = {row.section: row.data for row in global_rows}
        country_rows = (
            db.query(CountrySettings)
            .filter(CountrySettings.country_id == country_id)
            .all()
        )
        for row in country_rows:
            merged[row.section] = row.data
        return merged

    @staticmethod
    def seed_from_global(db: Session, country_id: int) -> list[str]:
        """Copy AppSettings rows into CountrySettings for a new country. Idempotent."""
        global_rows = db.query(AppSettings).all()
        seeded: list[str] = []
        for row in global_rows:
            exists = (
                db.query(CountrySettings)
                .filter(
                    CountrySettings.country_id == country_id,
                    CountrySettings.section == row.section,
                )
                .first()
            )
            if not exists:
                db.add(
                    CountrySettings(
                        country_id=country_id,
                        section=row.section,
                        data=row.data,
                        updated_by="seed",
                    )
                )
                seeded.append(row.section)
        db.commit()
        return seeded
