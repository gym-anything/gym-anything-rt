"""Seeded, continuous motion used by the four September 29 variants."""
import math


def noise(seed, index):
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967295 * 2 - 1


def motion(seed, milliseconds, span=1600):
    u = max(0, milliseconds) / span
    n = math.floor(u)
    f = u - n
    a, b = noise(seed, n), noise(seed, n + 1)
    return a + (b - a) * f * f * (3 - 2 * f)


def integral(seed, milliseconds, span=1600):
    u = max(0, milliseconds) / span
    n = math.floor(u)
    f = u - n
    total = sum((noise(seed, i) + noise(seed, i + 1)) / 2 for i in range(n))
    a, b = noise(seed, n), noise(seed, n + 1)
    return span * (total + a * f + (b - a) * (f**3 - f**4 / 2))


def vector(spec, milliseconds):
    return [a * motion(spec['seed'] + i * 7919, milliseconds, spec['span_ms'])
            for i, a in enumerate(spec['amplitude'])]
