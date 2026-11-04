"""Shared pydantic field types."""
from typing import Annotated

from pydantic import Field

# Plain syntactic e-mail check. pydantic's EmailStr (email-validator) rejects special-use TLDs such as
# `.local`, which are used for demo/seed accounts and on-premises deployments.
Email = Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)]
