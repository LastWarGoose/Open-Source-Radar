from packaging.version import Version


def nearest_version[T](available: dict[Version, T], target: Version) -> T | None:
    """Prefer the same release series, then the preceding release, then the next."""
    if target in available:
        return available[target]
    best = -1
    candidates: list[Version] = []
    for version in available:
        prefix = 0
        for a, b in zip(
            (version.epoch, *version.release), (target.epoch, *target.release), strict=False
        ):
            if a != b:
                break
            prefix += 1
        if prefix > best:
            best = prefix
            candidates.clear()
        if prefix == best:
            candidates.append(version)
    if not candidates:
        return None
    prior = max((v for v in candidates if v < target), default=None)
    return available[prior if prior is not None else min(candidates)]
