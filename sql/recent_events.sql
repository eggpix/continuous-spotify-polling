SELECT
    t.name AS track_name,
    al.name AS album_name,
    ph.started_at AT TIME ZONE 'America/Phoenix' AS start_date,
    ROUND(
        GREATEST(
            COALESCE(ph.playback_end, t.duration_ms)
            - COALESCE(ph.playback_start, 0),
            0
        ) / 60000.0,
        2
    ) AS listening_minutes
FROM playback_history ph
JOIN tracks t
    ON t.id = ph.track_id
JOIN albums al
    ON al.id = t.album_id
ORDER BY
    ph.started_at DESC;