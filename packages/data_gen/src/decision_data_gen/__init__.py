"""Générateur de données synthétiques Wave (Sénégal) pour le schéma raw."""

from .generate import Dataset, generate
from .serialize import data_hash

__all__ = ["Dataset", "data_hash", "generate"]
