import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from harambeeone_api.database import get_engine
from harambeeone_api.models import AcademicClass, FeeStructure, School, Stream

CLASS_PRESETS = [
    ("Baby", "nursery"),
    ("Middle", "nursery"),
    ("Top", "nursery"),
    ("P.1", "primary"),
    ("P.2", "primary"),
    ("P.3", "primary"),
    ("P.4", "primary"),
    ("P.5", "primary"),
    ("P.6", "primary"),
    ("P.7", "primary"),
    ("S.1", "secondary"),
    ("S.2", "secondary"),
    ("S.3", "secondary"),
    ("S.4", "secondary"),
    ("S.5", "secondary"),
    ("S.6", "secondary"),
]


def main() -> None:
    with Session(get_engine()) as session:
        school = session.scalar(select(School).where(School.name == "Kampala Community School"))
        if school is None:
            school = School(id=uuid.uuid4(), name="Kampala Community School", district="Kampala")
            session.add(school)
            session.flush()
        existing = set(
            session.scalars(select(AcademicClass.name).where(AcademicClass.school_id == school.id))
        )
        for order, (name, level) in enumerate(CLASS_PRESETS, start=1):
            if name in existing:
                continue
            academic_class = AcademicClass(
                id=uuid.uuid4(), school_id=school.id, name=name, level=level, sort_order=order
            )
            session.add(academic_class)
            session.flush()
            if level in {"primary", "secondary"}:
                session.add_all(
                    [
                        Stream(id=uuid.uuid4(), class_id=academic_class.id, name="North"),
                        Stream(id=uuid.uuid4(), class_id=academic_class.id, name="South"),
                    ]
                )
        session.flush()
        fee_class_ids = set(
            session.scalars(
                select(FeeStructure.class_id).where(FeeStructure.school_id == school.id)
            )
        )
        for academic_class in session.scalars(
            select(AcademicClass).where(AcademicClass.school_id == school.id)
        ):
            if academic_class.id not in fee_class_ids:
                amount = (
                    Decimal("850000") if academic_class.level == "nursery" else Decimal("1250000")
                )
                if academic_class.level == "secondary":
                    amount = Decimal("1850000")
                session.add(
                    FeeStructure(
                        id=uuid.uuid4(),
                        school_id=school.id,
                        class_id=academic_class.id,
                        name=f"{academic_class.name} Term 2 Fees",
                        academic_year=2026,
                        term=2,
                        total_amount=amount,
                    )
                )
        session.commit()
        print("Academic structure ready")


if __name__ == "__main__":
    main()
