-- Dhamma Sudha (Hastinapur) course list
-- Source: https://www.dhamma.org/en/schedules/schsudha  (fetched 2026-07-12)
-- Table: courses (c_type → course_types.ct_id, c_date = arrival / zero day)
--
-- course_types used:
--   1 = 10 Day
--   5 = STP (Satipatthana Sutta)
--   6 = 3 Day
--
-- Apply:
--   mysql -u gong -p gong < db/courses-sudha-2026-2027.sql
-- Or only replace from a date:
--   DELETE FROM courses WHERE c_date >= '2026-07-01';
--   then run the INSERT below.

-- Optional full reload of the listed window (uncomment if desired):
-- DELETE FROM courses WHERE c_date >= '2026-07-01';

INSERT INTO courses (c_type, c_date) VALUES
-- ========== 2026 ==========
-- 10-Day (remaining / open)
(1, '2026-07-15'),  -- 15 Jul – 26 Jul  10-Day
(1, '2026-08-05'),  -- 05 Aug – 16 Aug 10-Day
(1, '2026-08-19'),  -- 19 Aug – 30 Aug 10-Day
(1, '2026-09-02'),  -- 02 Sep – 13 Sep 10-Day
(1, '2026-09-16'),  -- 16 Sep – 27 Sep 10-Day
(1, '2026-10-07'),  -- 07 Oct – 18 Oct 10-Day
(5, '2026-10-21'),  -- 21 Oct – 29 Oct Satipatthana (STP)
(1, '2026-11-18'),  -- 18 Nov – 29 Nov 10-Day
(1, '2026-12-02'),  -- 02 Dec – 13 Dec 10-Day
(1, '2026-12-16'),  -- 16 Dec – 27 Dec 10-Day

-- 3-Day short courses (old students)
(6, '2026-07-30'),  -- 30 Jul – 02 Aug 3-Day
(6, '2026-11-04'),  -- 04 Nov – 07 Nov 3-Day
(6, '2026-11-12'),  -- 12 Nov – 15 Nov 3-Day

-- ========== 2027 ==========
-- 10-Day
(1, '2027-01-06'),  -- 06 Jan – 17 Jan 10-Day
(1, '2027-01-20'),  -- 20 Jan – 31 Jan 10-Day
(1, '2027-02-03'),  -- 03 Feb – 14 Feb 10-Day
(1, '2027-02-17'),  -- 17 Feb – 28 Feb 10-Day
(1, '2027-03-03'),  -- 03 Mar – 14 Mar 10-Day
(1, '2027-03-17'),  -- 17 Mar – 28 Mar 10-Day
(1, '2027-04-07'),  -- 07 Apr – 18 Apr 10-Day
(1, '2027-04-21'),  -- 21 Apr – 02 May 10-Day
(1, '2027-05-05'),  -- 05 May – 16 May 10-Day
(1, '2027-05-19'),  -- 19 May – 30 May 10-Day
(1, '2027-06-02'),  -- 02 Jun – 13 Jun 10-Day
(1, '2027-06-16'),  -- 16 Jun – 27 Jun 10-Day
(1, '2027-07-07'),  -- 07 Jul – 18 Jul 10-Day
(1, '2027-07-21'),  -- 21 Jul – 01 Aug 10-Day
(1, '2027-08-04'),  -- 04 Aug – 15 Aug 10-Day
(1, '2027-08-18'),  -- 18 Aug – 29 Aug 10-Day
(1, '2027-09-01'),  -- 01 Sep – 12 Sep 10-Day
(1, '2027-09-15'),  -- 15 Sep – 26 Sep 10-Day
(1, '2027-10-06'),  -- 06 Oct – 17 Oct 10-Day
(5, '2027-10-20'),  -- 20 Oct – 28 Oct Satipatthana (STP)
(1, '2027-11-03'),  -- 03 Nov – 14 Nov 10-Day
(1, '2027-11-17'),  -- 17 Nov – 28 Nov 10-Day
(1, '2027-12-01'),  -- 01 Dec – 12 Dec 10-Day
(1, '2027-12-15'),  -- 15 Dec – 26 Dec 10-Day

-- 3-Day short courses
(6, '2027-04-01'),  -- 01 Apr – 04 Apr 3-Day
(6, '2027-07-01');  -- 01 Jul – 04 Jul 3-Day
