SELECT
    t.name AS track_name,
    al.name AS album_name,
    ROUND(
        SUM(
            GREATEST(
                COALESCE(ph.playback_end, t.duration_ms)
                - COALESCE(ph.playback_start, 0),
                0
            )
        ) / 60000.0,
        2
    ) AS total_minutes_listened
FROM playback_history ph
JOIN tracks t
    ON t.id = ph.track_id
JOIN albums al
    ON al.id = t.album_id
WHERE
    ph.started_at >= TIMESTAMPTZ '2026-01-01 00:00:00 America/Phoenix'
    AND ph.started_at < TIMESTAMPTZ '2027-01-01 00:00:00 America/Phoenix'
GROUP BY
    t.id,
    t.name,
    al.name
ORDER BY
    total_minutes_listened DESC;