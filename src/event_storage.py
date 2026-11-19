def save_event(db, event):
    db.insert_track(event["track"])
    db.insert_event(
        event["track_id"],
        event["started_at"],
        event["playback_start"],
        event["playback_end"]
    )
    db.commit()
