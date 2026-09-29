-- Run this whole file in pgAdmin4 (Query Tool) while connected to the cellz_db database
CREATE TABLE IF NOT EXISTS admins (
  id SERIAL PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sectors (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  sort_order INT DEFAULT 0
);
CREATE TABLE IF NOT EXISTS brands (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS creatives (
  id SERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  sector_id INT NOT NULL REFERENCES sectors(id) ON DELETE RESTRICT,
  brand_id  INT NOT NULL REFERENCES brands(id)  ON DELETE RESTRICT,
  media_type TEXT NOT NULL CHECK (media_type IN ('image','video')),
  file_path TEXT NOT NULL,
  view_count INT NOT NULL DEFAULT 0,
  view_seconds INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS site_media (
  id SERIAL PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('hero','slider')),
  media_type TEXT NOT NULL,
  file_path TEXT NOT NULL,
  sort_order INT DEFAULT 0
);
CREATE TABLE IF NOT EXISTS daily_visits (
  day DATE PRIMARY KEY,
  visits INT NOT NULL DEFAULT 0
);

INSERT INTO sectors (name, sort_order) VALUES
 ('Graphics Design',1),('Motion Graphics',2),('Video Editing',3),('Photography',4),('Branding & Logo Design',5)
ON CONFLICT (name) DO NOTHING;
INSERT INTO brands (name) VALUES
 ('Burger King'),('Dominos'),('UAC'),('Cway'),('EatNGo'),('Ocado')
ON CONFLICT (name) DO NOTHING;
