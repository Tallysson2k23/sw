BEGIN;
ALTER TABLE courses ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0;
CREATE TABLE course_photos (
 id INTEGER PRIMARY KEY,
 course_id INTEGER NOT NULL REFERENCES courses(id),
 filename TEXT NOT NULL,
 caption TEXT NOT NULL,
 sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX course_photo_order ON course_photos(course_id, sort_order, id);
CREATE TABLE announcements (
 id INTEGER PRIMARY KEY,
 title TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 filename TEXT NOT NULL,
 link TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1,
 sort_order INTEGER NOT NULL DEFAULT 0
);
INSERT INTO schema_migrations VALUES(2);
COMMIT;
