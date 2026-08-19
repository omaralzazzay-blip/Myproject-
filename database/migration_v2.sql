-- ============================================================
--  ترحيل v2 - نظام إدارة المشاريع الإنشائية (حافظ على البيانات)
-- ============================================================
SET NAMES utf8mb4;
CREATE DATABASE IF NOT EXISTS construction_management
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE construction_management;

-- ---------- 1) أنواع/ أصناف المادة (مثال الخشب -> كرد/ألواح/مرابيع) ----------
CREATE TABLE IF NOT EXISTS material_types (
  id INT AUTO_INCREMENT PRIMARY KEY,
  material_id INT NOT NULL,
  name_ar VARCHAR(200) NOT NULL,
  code VARCHAR(50) DEFAULT NULL,
  notes VARCHAR(255) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_mt_mat FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE,
  UNIQUE KEY uq_mt (material_id, name_ar)
) ENGINE=InnoDB;

-- ---------- 2) ربط المادة بعدة وحدات قياس (M2M) ----------
CREATE TABLE IF NOT EXISTS material_units (
  id INT AUTO_INCREMENT PRIMARY KEY,
  material_id INT NOT NULL,
  unit_id INT NOT NULL,
  conversion_factor DECIMAL(18,3) NOT NULL DEFAULT 1 COMMENT 'معامل التحويل مقارنة بالوحدة الأساسية',
  is_default TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_mu_mat FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE,
  CONSTRAINT fk_mu_unit FOREIGN KEY (unit_id) REFERENCES units(id),
  UNIQUE KEY uq_mu (material_id, unit_id)
) ENGINE=InnoDB;

INSERT IGNORE INTO material_units (material_id, unit_id, conversion_factor, is_default)
SELECT m.id, m.unit_id, 1, 1 FROM materials m
WHERE NOT EXISTS (SELECT 1 FROM material_units mu WHERE mu.material_id=m.id AND mu.is_default=1);

-- ---------- 3) التالف في المخازن (لكل مخزن + مادة + نوع + وحدة) ----------
CREATE TABLE IF NOT EXISTS damaged_stock (
  id INT AUTO_INCREMENT PRIMARY KEY,
  warehouse_id INT NOT NULL,
  material_id INT NOT NULL,
  material_type_id INT DEFAULT NULL,
  unit_id INT NOT NULL,
  quantity DECIMAL(18,3) NOT NULL DEFAULT 0,
  reason VARCHAR(255) DEFAULT NULL,
  damaged_date DATE NOT NULL,
  reported_by INT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ds_wh FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE,
  CONSTRAINT fk_ds_mat FOREIGN KEY (material_id) REFERENCES materials(id),
  CONSTRAINT fk_ds_mt FOREIGN KEY (material_type_id) REFERENCES material_types(id) ON DELETE SET NULL,
  CONSTRAINT fk_ds_unit FOREIGN KEY (unit_id) REFERENCES units(id),
  CONSTRAINT fk_ds_user FOREIGN KEY (reported_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------- 4) بنود المصاريف/المسحوبات (عامل/مشرف + مادة) ----------
CREATE TABLE IF NOT EXISTS expense_lines (
  id INT AUTO_INCREMENT PRIMARY KEY,
  expense_id INT DEFAULT NULL,
  withdrawal_id INT DEFAULT NULL,
  line_type ENUM('worker','supervisor','material','other') NOT NULL DEFAULT 'other',
  worker_id INT DEFAULT NULL,
  supervisor_user_id INT DEFAULT NULL,
  material_id INT DEFAULT NULL,
  material_type_id INT DEFAULT NULL,
  unit_id INT DEFAULT NULL,
  quantity DECIMAL(18,3) DEFAULT 0,
  unit_price DECIMAL(18,3) DEFAULT 0,
  total_local DECIMAL(18,3) NOT NULL DEFAULT 0,
  description VARCHAR(255) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_el_exp FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE CASCADE,
  CONSTRAINT fk_el_wd FOREIGN KEY (withdrawal_id) REFERENCES withdrawals(id) ON DELETE CASCADE,
  CONSTRAINT fk_el_worker FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE SET NULL,
  CONSTRAINT fk_el_sup FOREIGN KEY (supervisor_user_id) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_el_mat FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL,
  CONSTRAINT fk_el_mt FOREIGN KEY (material_type_id) REFERENCES material_types(id) ON DELETE SET NULL,
  CONSTRAINT fk_el_unit FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------- 5) حساب كل عامل ----------
CREATE TABLE IF NOT EXISTS worker_account (
  id INT AUTO_INCREMENT PRIMARY KEY,
  worker_id INT NOT NULL,
  opening_balance DECIMAL(18,3) NOT NULL DEFAULT 0,
  notes VARCHAR(255) DEFAULT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_wa_worker FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE,
  UNIQUE KEY uq_wa_worker (worker_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS worker_account_moves (
  id INT AUTO_INCREMENT PRIMARY KEY,
  worker_id INT NOT NULL,
  move_type ENUM('debit','credit') NOT NULL COMMENT 'debit=مدين(عليه)/credit=دائن(له)',
  amount DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  reference_type VARCHAR(50) DEFAULT NULL,
  reference_id INT DEFAULT NULL,
  note VARCHAR(255) DEFAULT NULL,
  move_date DATE NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_wam_worker FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE,
  CONSTRAINT fk_wam_cur FOREIGN KEY (currency_id) REFERENCES currencies(id)
) ENGINE=InnoDB;

-- ---------- 6) حساب المشرف ----------
CREATE TABLE IF NOT EXISTS supervisor_account (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  opening_balance DECIMAL(18,3) NOT NULL DEFAULT 0,
  notes VARCHAR(255) DEFAULT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_sa_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  UNIQUE KEY uq_sa_user (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS supervisor_account_moves (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  move_type ENUM('debit','credit') NOT NULL,
  amount DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  reference_type VARCHAR(50) DEFAULT NULL,
  reference_id INT DEFAULT NULL,
  note VARCHAR(255) DEFAULT NULL,
  move_date DATE NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_sam_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_sam_cur FOREIGN KEY (currency_id) REFERENCES currencies(id)
) ENGINE=InnoDB;

-- ---------- 7) حسابات المشروع (مدين/دائن) - معترف وقت التحصيل ----------
CREATE TABLE IF NOT EXISTS project_account_entries (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  entry_type ENUM('receivable','payable') NOT NULL COMMENT 'receivable=مدين(لنا)/payable=دائن(علينا)',
  party_name VARCHAR(200) NOT NULL,
  description VARCHAR(255) DEFAULT NULL,
  amount DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  exchange_rate DECIMAL(18,6) NOT NULL DEFAULT 1,
  amount_local DECIMAL(18,3) NOT NULL DEFAULT 0,
  is_recognized TINYINT(1) NOT NULL DEFAULT 0,
  recognized_date DATE DEFAULT NULL,
  recognized_amount_local DECIMAL(18,3) DEFAULT 0,
  entry_date DATE NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_pae_proj FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_pae_cur FOREIGN KEY (currency_id) REFERENCES currencies(id)
) ENGINE=InnoDB;

-- ---------- 8) مرفقات الفواتير والمخططات ----------
CREATE TABLE IF NOT EXISTS attachments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  related_type VARCHAR(50) NOT NULL COMMENT 'purchase/supplier_delivery/project/expense/withdrawal',
  related_id INT DEFAULT NULL,
  project_id INT DEFAULT NULL,
  file_type ENUM('invoice','drawing','document','other') NOT NULL,
  original_name VARCHAR(255) NOT NULL,
  stored_name VARCHAR(255) NOT NULL,
  mime_type VARCHAR(100) DEFAULT NULL,
  file_size INT DEFAULT 0,
  description VARCHAR(255) DEFAULT NULL,
  uploaded_by INT DEFAULT NULL,
  uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_att_user FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE INDEX idx_att_rel ON attachments(related_type, related_id);
CREATE INDEX idx_pae_proj ON project_account_entries(project_id);
CREATE INDEX idx_wa_moves_worker ON worker_account_moves(worker_id);
CREATE INDEX idx_damaged ON damaged_stock(warehouse_id, material_id);

-- بيانات تجريبية للنظام الجديد
INSERT INTO material_types (material_id, name_ar, code, notes) VALUES
  (5, 'كرد', 'WOOD-K', 'كرد خشب'),
  (5, 'ألواح', 'WOOD-B', 'ألواح خشبية'),
  (5, 'مرابيع', 'WOOD-M', 'مرابيع خشبية');

INSERT INTO worker_account (worker_id, opening_balance, notes)
SELECT id, 0, 'حساب افتراضي' FROM workers WHERE NOT EXISTS (SELECT 1 FROM worker_account wa WHERE wa.worker_id=workers.id);

INSERT INTO material_units (material_id, unit_id, conversion_factor, is_default)
SELECT m.id, m.unit_id, 1, 1 FROM materials m
WHERE NOT EXISTS (SELECT 1 FROM material_units mu WHERE mu.material_id=m.id AND mu.is_default=1);
