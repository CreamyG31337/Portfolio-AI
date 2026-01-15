CREATE OR REPLACE VIEW fund_thesis_with_pillars AS  SELECT ft.id AS thesis_id,
    ft.fund,
    ft.title,
    ft.overview,
    ft.created_at AS thesis_created_at,
    ft.updated_at AS thesis_updated_at,
    ftp.id AS pillar_id,
    ftp.name AS pillar_name,
    ftp.allocation,
    ftp.thesis AS pillar_thesis,
    ftp.pillar_order,
    ftp.created_at AS pillar_created_at,
    ftp.updated_at AS pillar_updated_at
   FROM (fund_thesis ft
     LEFT JOIN fund_thesis_pillars ftp ON ((ft.id = ftp.thesis_id)))
  ORDER BY ft.fund, ftp.pillar_order;