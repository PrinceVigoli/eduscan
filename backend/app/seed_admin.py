import getpass

from sqlalchemy import select

from .database import Base, SessionLocal, engine
from .models import User, UserRole
from .security import hash_password


def main() -> None:
    Base.metadata.create_all(bind=engine)
    email = input("IT administrator email: ").strip().lower()
    full_name = input("Full name: ").strip()
    password = getpass.getpass("Password (minimum 10 characters): ")
    if len(password) < 10:
        raise SystemExit("Password is too short.")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            raise SystemExit("That email already exists.")
        db.add(User(full_name=full_name, email=email, role=UserRole.administrator, password_hash=hash_password(password)))
        db.commit()
    print("IT administrator created.")


if __name__ == "__main__":
    main()
