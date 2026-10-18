-- Historique des alertes des deux niveaux (N1 et N2).
-- Rempli par alertsink, lu par Grafana (tableau de bord « Alertes »).
-- PostgreSQL exécute ce fichier une seule fois, à la création du volume rt3p9-alertdb.

-- Une ligne par occurrence d'alerte, de son déclenchement à sa résolution.
CREATE TABLE alerts (
    id           bigserial   PRIMARY KEY,
    fingerprint  text        NOT NULL,      -- identifiant Alertmanager (calculé sur les étiquettes)
    starts_at    timestamptz NOT NULL,      -- début, selon Prometheus
    ends_at      timestamptz,               -- fin, selon Prometheus (vide tant qu'elle est active)
    received_at  timestamptz NOT NULL,      -- réception du déclenchement par alertsink (t_detect)
    resolved_at  timestamptz,               -- réception de la résolution par alertsink
    level        text,                      -- N1 ou N2 (test pour les alertes de make check)
    alertname    text,                      -- règle : LinkSaturation, PortScan…
    router       text,                      -- routeur concerné
    interface    text,                      -- interface concernée (règles de débit)
    summary      text,                      -- résumé lisible, défini dans la règle
    labels       jsonb       NOT NULL,      -- toutes les étiquettes de l'alerte
    UNIQUE (fingerprint, starts_at)
);

CREATE INDEX alerts_starts_at ON alerts (starts_at);
