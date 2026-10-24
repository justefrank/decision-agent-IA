# decision-data-gen

Générateur de données synthétiques « Wave Sénégal » pour le schéma `raw` (rôle `dbt_owner`),
chargées par `COPY` en une transaction.

```bash
uv run python -m decision_data_gen --scale 1.0 --seed 42 --dsn postgresql://dbt_owner:…@localhost:5432/warehouse
uv run python -m decision_data_gen --scale 0.01 --dry-run   # sans base : imprime data_hash
```

| Échelle | Clients | Agents | Transactions | Durée (génération + COPY) |
|---|---|---|---|---|
| 1.0 | 50 000 | 2 000 | 2 200 000 | ≈ 11 s |
| 0.02 | 1 000 | 40 | 44 000 | < 1 s |

Tables : `raw_regions` (14), `raw_holidays` (jours fériés 2025-2026), `raw_clients`, `raw_agents`
(`date_fermeture` pour les agents fermés), `raw_transactions` (`agent_id` NULL = hors agent),
`raw_meta` (graine, échelle, `data_hash`).

Profil : 18 mois (2025-04-01 → 2026-09-30 = REFERENCE_DATE), croissance ≈ +60 %, fins et débuts
de mois (salaires), veilles de Tabaski, Korité, Magal et Noël, creux du dimanche et des jours
fériés ; ≈ 6 % d'échecs (plus pour les paiements, les jours de pointe, les régions à réseau
fragile, les gros montants) ; transferts et paiements hors agent ≈ 12,5 % ; Dakar ≈ 38 % ;
montants log-normaux arrondis à 5 XOF avec 0,04 % de valeurs aberrantes ; frais : dépôts
gratuits, retraits, transferts et paiements à 1 %, échecs non facturés ; quelques noms d'agents
« sales » (texte libre non fiable, dont une tentative d'injection volontaire).

Déterminisme : un seul `numpy.random.Generator(PCG64(seed))` ; `data_hash` = SHA-256 des octets
envoyés à `COPY` (identique avec `--dry-run`). Valable à version de numpy égale (figée par `uv.lock`).

Tests : `uv run pytest packages/data_gen -q` (déterminisme, contraintes, saisonnalité, synchronisation
du modèle dbt `kpi_reference` avec `semantic/kpis.yaml`) ; chargement réel opt-in avec
`DATA_GEN_TEST_DSN`.
