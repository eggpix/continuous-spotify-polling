SELECT
    ar.name AS artist_name,
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
JOIN track_artists ta
    ON ta.track_id = t.id
JOIN artists ar
    ON ar.id = ta.artist_id
GROUP BY
    ar.id,
    ar.name
ORDER BY
    total_minutes_listened DESC;
