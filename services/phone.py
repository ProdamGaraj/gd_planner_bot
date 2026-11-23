import re


def validate_phone(phone: str) -> tuple[bool, str]:
    """Разрешены номера Узбекистана (+998) и России/Казахстана (+7).

    Возвращает (валиден, нормализованный номер вида +998901234567).
    """
    cleaned = re.sub(r"[\s\-()]+", "", phone or "")
    if not re.fullmatch(r"\+?\d+", cleaned):
        return False, ""

    digits = cleaned.lstrip("+")
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]

    if digits.startswith("998") and len(digits) == 12:
        return True, "+" + digits
    if digits.startswith("7") and len(digits) == 11:
        return True, "+" + digits
    return False, ""
