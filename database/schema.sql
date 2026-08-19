-- ============================================================
--  نظام إدارة المشاريع الإنشائية - مخطط قاعدة البيانات
--  MySQL / MariaDB (XAMPP)
--  النسخة الموسعة: أنواع المواد، وحدات متعددة، قسم التالف،
--  المصروفات والمسحوبات (عامل/مشرف/مادة)، قائمة الحسابات
--  (مدين/دائن)، والمرفقات.
--  الاستيراد: phpMyAdmin => استيراد => اختيار هذا الملف
-- ============================================================
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE DATABASE IF NOT EXISTS construction_management
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE construction_management;

DROP TABLE IF EXISTS attachments, account_entries, accounts, issues,
  damaged_goods, material_units, material_types,
  notifications, stock_movements, withdrawals, expenses,
  supplier_deliveries, supplier_money, suppliers, funder_deposits, funders,
  budgets, worker_withdrawals, worker_deductions, worker_attendance, workers,
  users, worker_types, materials, units, warehouses, phases, projects, currencies;

-- ---------- العملات ----------
CREATE TABLE currencies (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(10) NOT NULL UNIQUE,
  name_ar VARCHAR(100) NOT NULL,
  rate_to_local DECIMAL(18,6) NOT NULL DEFAULT 1 COMMENT 'قيمة وحدة العملة مقابل العملة المحلية',
  is_local TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------- المشاريع ----------
CREATE TABLE projects (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  code VARCHAR(50) DEFAULT NULL,
  location VARCHAR(200) DEFAULT NULL,
  start_date DATE DEFAULT NULL,
  end_date DATE DEFAULT NULL,
  status ENUM('planned','active','paused','finished') DEFAULT 'active',
  description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------- المراحل ----------
CREATE TABLE phases (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  name VARCHAR(200) NOT NULL,
  description TEXT,
  start_date DATE DEFAULT NULL,
  end_date DATE DEFAULT NULL,
  status ENUM('planned','active','done') DEFAULT 'active',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_phases_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------- المخازن ----------
CREATE TABLE warehouses (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  name VARCHAR(200) NOT NULL,
  location VARCHAR(200) DEFAULT NULL,
  manager_name VARCHAR(100) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_wh_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------- وحدات القياس ----------
CREATE TABLE units (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name_ar VARCHAR(100) NOT NULL UNIQUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------- المواد ----------
CREATE TABLE materials (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name_ar VARCHAR(200) NOT NULL,
  unit_id INT NOT NULL COMMENT 'وحدة القياس الأساسية',
  price_per_unit DECIMAL(18,3) DEFAULT 0,
  currency_id INT DEFAULT NULL,
  has_damage TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'تفعيل قسم التالف (مفعل افتراضياً لكل المواد)',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_mat_unit FOREIGN KEY (unit_id) REFERENCES units(id),
  CONSTRAINT fk_mat_cur FOREIGN KEY (currency_id) REFERENCES currencies(id)
) ENGINE=InnoDB;

-- ---------- الأنواع الفرعية للمادة (مثال: خشب كرد / ألواح / مرابيع) ----------
CREATE TABLE material_types (
  id INT AUTO_INCREMENT PRIMARY KEY,
  material_id INT NOT NULL,
  name_ar VARCHAR(200) NOT NULL,
  has_damage TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'قسم تالف لهذا النوع',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_mt_mat FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE,
  UNIQUE KEY uq_mt (material_id, name_ar)
) ENGINE=InnoDB;

-- ---------- وحدات قياس متعددة لكل مادة (بالإضافة للوحدة الأساسية) ----------
CREATE TABLE material_units (
  id INT AUTO_INCREMENT PRIMARY KEY,
  material_id INT NOT NULL,
  unit_id INT NOT NULL,
  factor DECIMAL(18,6) NOT NULL DEFAULT 1 COMMENT 'معامل التحويل إلى الوحدة الأساسية (توثيقي)',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_mu_mat FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE,
  CONSTRAINT fk_mu_unit FOREIGN KEY (unit_id) REFERENCES units(id),
  UNIQUE KEY uq_mu (material_id, unit_id)
) ENGINE=InnoDB;

-- ---------- أنواع العمال ----------
CREATE TABLE worker_types (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name_ar VARCHAR(100) NOT NULL UNIQUE,
  default_wage DECIMAL(18,3) DEFAULT 0,
  currency_id INT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_wt_cur FOREIGN KEY (currency_id) REFERENCES currencies(id)
) ENGINE=InnoDB;

-- ---------- المستخدمون (مدير / مشرف) ----------
CREATE TABLE users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(100) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  full_name VARCHAR(200) NOT NULL,
  role ENUM('admin','supervisor') NOT NULL DEFAULT 'supervisor',
  project_id INT DEFAULT NULL COMMENT 'المشروع المرتبط بالمشرف',
  phone VARCHAR(50) DEFAULT NULL,
  is_active TINYINT(1) DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_user_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------- العمال ----------
CREATE TABLE workers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  phase_id INT NOT NULL,
  name VARCHAR(200) NOT NULL,
  phone VARCHAR(50) DEFAULT NULL,
  worker_type_id INT NOT NULL,
  wage_per_day DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  status ENUM('active','stopped') DEFAULT 'active',
  joined_date DATE DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_worker_phase FOREIGN KEY (phase_id) REFERENCES phases(id) ON DELETE CASCADE,
  CONSTRAINT fk_worker_type FOREIGN KEY (worker_type_id) REFERENCES worker_types(id),
  CONSTRAINT fk_worker_cur FOREIGN KEY (currency_id) REFERENCES currencies(id)
) ENGINE=InnoDB;

-- ---------- دوام العمال ----------
CREATE TABLE worker_attendance (
  id INT AUTO_INCREMENT PRIMARY KEY,
  worker_id INT NOT NULL,
  work_date DATE NOT NULL,
  note VARCHAR(255) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_att_worker FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE,
  UNIQUE KEY uq_att (worker_id, work_date)
) ENGINE=InnoDB;

-- ---------- خصومات العمال ----------
CREATE TABLE worker_deductions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  worker_id INT NOT NULL,
  amount DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  reason VARCHAR(255) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ded_worker FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE,
  CONSTRAINT fk_ded_cur FOREIGN KEY (currency_id) REFERENCES currencies(id)
) ENGINE=InnoDB;

-- ---------- سحوبات العمال ----------
CREATE TABLE worker_withdrawals (
  id INT AUTO_INCREMENT PRIMARY KEY,
  worker_id INT NOT NULL,
  amount DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  note VARCHAR(255) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ww_worker FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE,
  CONSTRAINT fk_ww_cur FOREIGN KEY (currency_id) REFERENCES currencies(id)
) ENGINE=InnoDB;

-- ---------- الميزانيات (مالك / مشروع / مرحلة) ----------
CREATE TABLE budgets (
  id INT AUTO_INCREMENT PRIMARY KEY,
  level ENUM('owner','project','phase') NOT NULL,
  project_id INT DEFAULT NULL,
  phase_id INT DEFAULT NULL,
  source VARCHAR(100) DEFAULT NULL,
  amount DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  exchange_rate DECIMAL(18,6) NOT NULL DEFAULT 1,
  amount_local DECIMAL(18,3) NOT NULL DEFAULT 0,
  note VARCHAR(255) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_bud_proj FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_bud_phase FOREIGN KEY (phase_id) REFERENCES phases(id) ON DELETE CASCADE,
  CONSTRAINT fk_bud_cur FOREIGN KEY (currency_id) REFERENCES currencies(id)
) ENGINE=InnoDB;

-- ---------- الممولون ----------
CREATE TABLE funders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  phone VARCHAR(50) DEFAULT NULL,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------- تمويل الممولين للمشاريع ----------
CREATE TABLE funder_deposits (
  id INT AUTO_INCREMENT PRIMARY KEY,
  funder_id INT NOT NULL,
  project_id INT NOT NULL,
  amount DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  exchange_rate DECIMAL(18,6) NOT NULL DEFAULT 1,
  amount_local DECIMAL(18,3) NOT NULL DEFAULT 0,
  note VARCHAR(255) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_fd_funder FOREIGN KEY (funder_id) REFERENCES funders(id) ON DELETE CASCADE,
  CONSTRAINT fk_fd_proj FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_fd_cur FOREIGN KEY (currency_id) REFERENCES currencies(id)
) ENGINE=InnoDB;

-- ---------- الموردون ----------
CREATE TABLE suppliers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  phone VARCHAR(50) DEFAULT NULL,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------- توريد مبالغ مالية من المورد ----------
CREATE TABLE supplier_money (
  id INT AUTO_INCREMENT PRIMARY KEY,
  supplier_id INT NOT NULL,
  project_id INT NOT NULL,
  amount DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  exchange_rate DECIMAL(18,6) NOT NULL DEFAULT 1,
  amount_local DECIMAL(18,3) NOT NULL DEFAULT 0,
  note VARCHAR(255) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_sm_supp FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE CASCADE,
  CONSTRAINT fk_sm_proj FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_sm_cur FOREIGN KEY (currency_id) REFERENCES currencies(id)
) ENGINE=InnoDB;

-- ---------- توريد مواد من المورد ----------
CREATE TABLE supplier_deliveries (
  id INT AUTO_INCREMENT PRIMARY KEY,
  supplier_id INT NOT NULL,
  warehouse_id INT NOT NULL,
  material_id INT NOT NULL,
  material_type_id INT DEFAULT NULL,
  unit_id INT NOT NULL,
  quantity DECIMAL(18,3) NOT NULL DEFAULT 0,
  price_per_unit DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  exchange_rate DECIMAL(18,6) NOT NULL DEFAULT 1,
  total_local DECIMAL(18,3) NOT NULL DEFAULT 0,
  note VARCHAR(255) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_sd_supp FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE CASCADE,
  CONSTRAINT fk_sd_wh FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE,
  CONSTRAINT fk_sd_mat FOREIGN KEY (material_id) REFERENCES materials(id),
  CONSTRAINT fk_sd_mt FOREIGN KEY (material_type_id) REFERENCES material_types(id) ON DELETE SET NULL,
  CONSTRAINT fk_sd_unit FOREIGN KEY (unit_id) REFERENCES units(id),
  CONSTRAINT fk_sd_cur FOREIGN KEY (currency_id) REFERENCES currencies(id)
) ENGINE=InnoDB;

-- ---------- المصاريف ----------
CREATE TABLE expenses (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  phase_id INT DEFAULT NULL,
  category VARCHAR(100) DEFAULT 'أخرى',
  description VARCHAR(255) DEFAULT NULL,
  amount DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  exchange_rate DECIMAL(18,6) NOT NULL DEFAULT 1,
  amount_local DECIMAL(18,3) NOT NULL DEFAULT 0,
  expense_date DATE NOT NULL,
  created_by INT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_exp_proj FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_exp_phase FOREIGN KEY (phase_id) REFERENCES phases(id) ON DELETE SET NULL,
  CONSTRAINT fk_exp_cur FOREIGN KEY (currency_id) REFERENCES currencies(id),
  CONSTRAINT fk_exp_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------- المسحوبات ----------
CREATE TABLE withdrawals (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  phase_id INT DEFAULT NULL,
  description VARCHAR(255) DEFAULT NULL,
  amount DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  exchange_rate DECIMAL(18,6) NOT NULL DEFAULT 1,
  amount_local DECIMAL(18,3) NOT NULL DEFAULT 0,
  withdraw_date DATE NOT NULL,
  created_by INT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_wd_proj FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_wd_phase FOREIGN KEY (phase_id) REFERENCES phases(id) ON DELETE SET NULL,
  CONSTRAINT fk_wd_cur FOREIGN KEY (currency_id) REFERENCES currencies(id),
  CONSTRAINT fk_wd_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------- حركة المخازن (إدخال / صرف / إرجاع / تالف) ----------
CREATE TABLE stock_movements (
  id INT AUTO_INCREMENT PRIMARY KEY,
  warehouse_id INT NOT NULL,
  material_id INT NOT NULL,
  material_type_id INT DEFAULT NULL,
  unit_id INT NOT NULL,
  movement_type ENUM('in','out','return','damage') NOT NULL,
  quantity DECIMAL(18,3) NOT NULL DEFAULT 0,
  price_per_unit DECIMAL(18,3) DEFAULT 0,
  currency_id INT DEFAULT NULL,
  exchange_rate DECIMAL(18,6) DEFAULT 1,
  total_local DECIMAL(18,3) DEFAULT 0,
  issue_id INT DEFAULT NULL COMMENT 'القيد المرتبط بالمصروف/السحب (عند الصرف)',
  movement_date DATE NOT NULL,
  note VARCHAR(255) DEFAULT NULL,
  created_by INT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_sm2_wh FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE,
  CONSTRAINT fk_sm2_mat FOREIGN KEY (material_id) REFERENCES materials(id),
  CONSTRAINT fk_sm2_mt FOREIGN KEY (material_type_id) REFERENCES material_types(id) ON DELETE SET NULL,
  CONSTRAINT fk_sm2_unit FOREIGN KEY (unit_id) REFERENCES units(id),
  CONSTRAINT fk_sm2_cur FOREIGN KEY (currency_id) REFERENCES currencies(id),
  CONSTRAINT fk_sm2_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------- قسم التالف لكل مخزن / مادة / نوع ----------
CREATE TABLE damaged_goods (
  id INT AUTO_INCREMENT PRIMARY KEY,
  warehouse_id INT NOT NULL,
  material_id INT NOT NULL,
  material_type_id INT DEFAULT NULL,
  unit_id INT NOT NULL,
  quantity DECIMAL(18,3) NOT NULL DEFAULT 0,
  reason VARCHAR(255) DEFAULT NULL,
  value_local DECIMAL(18,3) DEFAULT 0,
  damage_date DATE NOT NULL,
  movement_id INT DEFAULT NULL,
  created_by INT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_dg_wh FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE,
  CONSTRAINT fk_dg_mat FOREIGN KEY (material_id) REFERENCES materials(id),
  CONSTRAINT fk_dg_mt FOREIGN KEY (material_type_id) REFERENCES material_types(id) ON DELETE SET NULL,
  CONSTRAINT fk_dg_unit FOREIGN KEY (unit_id) REFERENCES units(id),
  CONSTRAINT fk_dg_usr FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------- المصروفات والمسحوبات (عامل / مشرف / مادة) ----------
-- كل قيد يُخصم تلقائياً من حساب العامل أو المشرف المعني.
CREATE TABLE issues (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  warehouse_id INT DEFAULT NULL,
  material_id INT DEFAULT NULL,
  material_type_id INT DEFAULT NULL,
  unit_id INT DEFAULT NULL,
  quantity DECIMAL(18,3) DEFAULT 0,
  unit_price DECIMAL(18,3) DEFAULT 0,
  currency_id INT NOT NULL,
  exchange_rate DECIMAL(18,6) DEFAULT 1,
  total_local DECIMAL(18,3) DEFAULT 0,
  beneficiary_type ENUM('worker','supervisor') NOT NULL,
  worker_id INT DEFAULT NULL,
  supervisor_user_id INT DEFAULT NULL,
  issue_kind ENUM('material','cash') NOT NULL DEFAULT 'material',
  description VARCHAR(255),
  issue_date DATE NOT NULL,
  created_by INT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_iss_proj FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_iss_wh FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE SET NULL,
  CONSTRAINT fk_iss_mat FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL,
  CONSTRAINT fk_iss_mt FOREIGN KEY (material_type_id) REFERENCES material_types(id) ON DELETE SET NULL,
  CONSTRAINT fk_iss_unit FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE SET NULL,
  CONSTRAINT fk_iss_wk FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE SET NULL,
  CONSTRAINT fk_iss_sup FOREIGN KEY (supervisor_user_id) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_iss_usr FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------- قائمة الحسابات (مدين / دائن + حسابات العمال والمشرفين) ----------
-- المدين: يُعترف به عند تحصيله فعلياً (أساس الاستحقاق النقدي للمدين)
-- الدائن: يُخصم مباشرة من ميزانية المشروع
CREATE TABLE accounts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  name VARCHAR(200) NOT NULL,
  acc_type ENUM('project','worker','supervisor','debtor','creditor') NOT NULL,
  party_type ENUM('worker','user','supplier','funder','other') DEFAULT 'other',
  party_id INT DEFAULT NULL,
  collected TINYINT(1) DEFAULT 0 COMMENT 'للمدين: هل حُصّل المبلغ فعلياً',
  collection_date DATE DEFAULT NULL,
  description VARCHAR(255),
  is_main TINYINT(1) DEFAULT 0 COMMENT 'حساب المشروع الرئيسي',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_acc_proj FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------- قيود الحسابات (دائن/مدين) ----------
CREATE TABLE account_entries (
  id INT AUTO_INCREMENT PRIMARY KEY,
  account_id INT NOT NULL,
  project_id INT NOT NULL,
  direction ENUM('debit','credit') NOT NULL COMMENT 'debit=زيادة على الحساب، credit=خصم على الحساب',
  amount DECIMAL(18,3) NOT NULL DEFAULT 0,
  currency_id INT NOT NULL,
  exchange_rate DECIMAL(18,6) DEFAULT 1,
  amount_local DECIMAL(18,3) NOT NULL DEFAULT 0,
  ref_type VARCHAR(30) DEFAULT NULL COMMENT 'issue/collection/creditor/...',
  ref_id INT DEFAULT NULL,
  note VARCHAR(255),
  entry_date DATE NOT NULL,
  created_by INT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ae_acc FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
  CONSTRAINT fk_ae_proj FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_ae_cur FOREIGN KEY (currency_id) REFERENCES currencies(id),
  CONSTRAINT fk_ae_usr FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------- المرفقات (فواتير، مخططات، مستندات) ----------
CREATE TABLE attachments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  ref_type ENUM('expense','withdrawal','issue','supplier_delivery','supplier_money','funder_deposit','budget','project','general') DEFAULT 'general',
  ref_id INT DEFAULT NULL,
  file_name VARCHAR(255) NOT NULL COMMENT 'الاسم الأصلي للملف',
  stored_name VARCHAR(255) NOT NULL COMMENT 'الاسم المخزن على القرص',
  file_type VARCHAR(100),
  file_size INT,
  note VARCHAR(255),
  uploaded_by INT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_att_proj FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT fk_att_usr FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------- الإشعارات ----------
CREATE TABLE notifications (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  title VARCHAR(200) NOT NULL,
  message TEXT,
  type VARCHAR(50) DEFAULT 'info',
  link VARCHAR(255) DEFAULT NULL,
  is_read TINYINT(1) DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================
--  البيانات التجريبية
-- ============================================================
-- المستخدمون الافتراضيون:
--   المدير:   admin      / admin123
--   المشرف:   supervisor / 123456
INSERT INTO users (username, password_hash, full_name, role, project_id, phone, is_active) VALUES
('admin',      'scrypt:32768:8:1$PyMZAXLhEAgjWKTr$57e10d58bcea10c913627dc75d38cafcb5e088d1d95ab8438338d201256346097706e0e66a79143523802ce65cb659a22d41a9135321fec174f04f2e9697b2c5', 'مدير النظام', 'admin', NULL, '700000000', 1),
('supervisor', 'scrypt:32768:8:1$bW49S5T7APnsh4TV$bc92efcdcaf516a0a0e9f1877c786ae476b3cd04783ef9e19c6a35208fc4fd78de16348e05d3302d48c730e09fd31a72f4bfc33c5a299bf8458a6d361880f110', 'المشرف الأول', 'supervisor', 1, '711000000', 1);

INSERT INTO currencies (code, name_ar, rate_to_local, is_local) VALUES
('YER','ريال يمني',1,1),
('SAR','ريال سعودي',750,0),
('USD','دولار أمريكي',2800,0);

INSERT INTO units (name_ar) VALUES
('كيس'),('سيخ'),('طن'),('قسم'),('حبة'),('متر'),
('كرتون'),('عدد'),('درزن'),('متر مكعب'),('قطعة'),('دزينة'),('لتر'),('كيلو');

INSERT INTO materials (name_ar, unit_id, price_per_unit, currency_id, has_damage) VALUES
('إسمنت', 1, 4500, 1, 1),
('حديد تسليح 12', 2, 27500, 1, 1),
('حديد تسليح (بالطن)', 3, 1800000, 1, 1),
('حجر', 4, 15000, 1, 1),
('خشب', 11, 9500, 1, 1),
('رمل', 10, 85000, 1, 1);

-- أنواع فرعية للمواد (مثال: خشب كرد / ألواح / مرابيع)
INSERT INTO material_types (material_id, name_ar, has_damage) VALUES
(5,'خشب كرد',1),
(5,'خشب ألواح',1),
(5,'خشب مرابيع',1),
(2,'حديد 12م',1),
(2,'حديد 6م',1),
(1,'إسمنت عادي',1),
(1,'إسمنت مقاوم',1);

-- وحدات متعددة لكل مادة (إضافةً لوحدة المادة الأساسية)
INSERT INTO material_units (material_id, unit_id, factor) VALUES
(5,5,1),   -- خشب: قطعة = حبة (أساسية قطعة)
(5,6,3),   -- خشب: متر
(1,10,0.05),
(2,3,0.05);

INSERT INTO worker_types (name_ar, default_wage, currency_id) VALUES
('معلم', 7000, 1),
('نجار', 5000, 1),
('عامل', 4000, 1);

INSERT INTO projects (name, code, location, status, description) VALUES
('مشروع عمارة المالك', 'PRJ-001', 'صنعاء - حدة', 'active', 'عمارة سكنية من 5 طوابق'),
('مشروع مدرسة الأمل', 'PRJ-002', 'صنعاء - شملان', 'planned', 'مدرسة من دورين');

INSERT INTO phases (project_id, name, status, start_date) VALUES
(1,'مرحلة الأساسات','done','2026-01-10'),
(1,'مرحلة الهيكل','active','2026-03-01'),
(1,'مرحلة التشطيبات','planned','2026-08-01'),
(2,'مرحلة الحفر','active','2026-06-01');

INSERT INTO warehouses (project_id, name, location, manager_name) VALUES
(1,'المخزن الرئيسي','موقع العمارة - حدة','أبو محمد'),
(1,'مخزن الحديد','منطقة التخزين الشرقية','علي صالح'),
(2,'مخزن المدرسة','موقع شملان',NULL);

-- حساب المشروع الرئيسي لكل مشروع
INSERT INTO accounts (project_id, name, acc_type, is_main, description) VALUES
(1,'الحساب الرئيسي - مشروع عمارة المالك','project',1,'حساب المشروع الرئيسي'),
(2,'الحساب الرئيسي - مشروع مدرسة الأمل','project',1,'حساب المشروع الرئيسي');

INSERT INTO budgets (level, project_id, phase_id, source, amount, currency_id, exchange_rate, amount_local, note) VALUES
('owner',NULL,NULL,'رأس مال المالك',50000000,1,1,50000000,'رأس المال الأساسي للمالك'),
('project',1,NULL,'رأس مال المالك',40000000,1,1,40000000,'تخصيص المشروع الأول'),
('phase',1,1,'رأس مال المالك',8000000,1,1,8000000,'ميزانية الأساسات'),
('phase',1,2,'رأس مال المالك',12000000,1,1,12000000,'ميزانية الهيكل'),
('project',2,NULL,'رأس مال المالك',25000000,1,1,25000000,'ميزانية المدرسة');

INSERT INTO funders (name, phone, notes) VALUES
('مؤسسة الإعمار التنموية','777111222','ممول رئيسي'),
('صندوق المشاريع','733444555','تمويل جزئي');

INSERT INTO funder_deposits (funder_id, project_id, amount, currency_id, exchange_rate, amount_local, note) VALUES
(1,1,20000,3,2800,56000000,'دفعة تمويلية أولى بالدولار'),
(2,2,50000,2,750,37500000,'دفعة بالريال السعودي');

INSERT INTO suppliers (name, phone, notes) VALUES
('مؤسسة الصلب التجارية','711223344','مورد حديد'),
('شركة إسمنت اليمن','733445566','مورد إسمنت'),
('مورد الأخشاب','766778899',NULL);

INSERT INTO supplier_money (supplier_id, project_id, amount, currency_id, exchange_rate, amount_local, note) VALUES
(1,1,3000000,1,1,3000000,'مبلغ توريد مبدئي من المورد');

INSERT INTO supplier_deliveries (supplier_id, warehouse_id, material_id, material_type_id, unit_id, quantity, price_per_unit, currency_id, exchange_rate, total_local, note) VALUES
(2,1,1,6,1,500,4500,1,1,2250000,'دفعة إسمنت'),
(1,2,2,4,2,300,27500,1,1,8250000,'دفعة حديد 12'),
(3,1,5,1,11,150,9500,1,1,1425000,'أخشاب - كرد');

INSERT INTO workers (phase_id, name, phone, worker_type_id, wage_per_day, currency_id, status, joined_date) VALUES
(2,'أحمد حسن','700111222',1,7500,1,'active','2026-03-05'),
(2,'محمد علي','711222333',3,4000,1,'active','2026-03-05'),
(1,'صالح ناصر','722333444',2,5000,1,'active','2026-01-12'),
(2,'خالد عبدالله','733444555',3,4200,1,'active','2026-04-01'),
(3,'فؤاد قاسم','744555666',1,7000,1,'active','2026-08-02');

-- حسابات تجريبية للعمال والمشرف الأول
INSERT INTO accounts (project_id, name, acc_type, party_type, party_id, description) VALUES
(1,'حساب العامل: أحمد حسن','worker','worker',1,'حساب تلقائي للعامل أحمد'),
(1,'حساب العامل: محمد علي','worker','worker',2,'حساب تلقائي للعامل محمد'),
(1,'حساب المشرف: المشرف الأول','supervisor','user',2,'حساب المشرف الأول');

-- دوام تجريبي لآخر 10 أيام (عدا الجمعة والسبت)
INSERT INTO worker_attendance (worker_id, work_date, note)
SELECT w.id, d.d, NULL FROM workers w
JOIN (SELECT CURDATE() - INTERVAL n DAY AS d FROM (
  SELECT 0 n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
  UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9
) nums) d
WHERE w.id IN (1,2,4) AND DAYOFWEEK(d.d) NOT IN (1,7);

INSERT INTO worker_deductions (worker_id, amount, currency_id, reason) VALUES
(1,5000,1,'غياب يومين'),
(2,2000,1,'خصم أدوات تالفة');

INSERT INTO worker_withdrawals (worker_id, amount, currency_id, note) VALUES
(1,15000,1,'سلفة'),
(2,8000,1,'سلفة');

INSERT INTO expenses (project_id, phase_id, category, description, amount, currency_id, exchange_rate, amount_local, expense_date) VALUES
(1,2,'مواد','دفعة حديد إضافية',500000,1,1,500000,CURDATE() - INTERVAL 2 DAY),
(1,1,'نقل','نقل معدات للأساسات',120000,1,1,120000,CURDATE() - INTERVAL 9 DAY),
(1,2,'أخرى','أجور تشغيل معدات',200000,1,1,200000,CURDATE() - INTERVAL 1 DAY),
(2,4,'مواد','رمل وحصى',180000,1,1,180000,CURDATE() - INTERVAL 3 DAY);

INSERT INTO withdrawals (project_id, phase_id, description, amount, currency_id, exchange_rate, amount_local, withdraw_date) VALUES
(1,2,'سحب نقدي لدفع أجور العمال',300000,1,1,300000,CURDATE() - INTERVAL 2 DAY),
(1,2,'سحب لشراء إسمنت',225000,1,1,225000,CURDATE() - INTERVAL 5 DAY),
(2,4,'سحب تشغيل الموقع',100000,1,1,100000,CURDATE() - INTERVAL 4 DAY);

INSERT INTO stock_movements (warehouse_id, material_id, material_type_id, unit_id, movement_type, quantity, price_per_unit, currency_id, exchange_rate, total_local, movement_date, note) VALUES
(1,1,6,1,'in',200,4500,1,1,900000,CURDATE() - INTERVAL 6 DAY,'إدخال إسمنت'),
(1,1,6,1,'out',50,4500,1,1,225000,CURDATE() - INTERVAL 3 DAY,'صرف للموقع'),
(2,2,4,2,'in',100,27500,1,1,2750000,CURDATE() - INTERVAL 10 DAY,'إدخال حديد');

-- أمثلة تالف ومرتجع
INSERT INTO stock_movements (warehouse_id, material_id, material_type_id, unit_id, movement_type, quantity, price_per_unit, currency_id, exchange_rate, total_local, movement_date, note) VALUES
(1,1,6,1,'damage',2,4500,1,1,9000,CURDATE() - INTERVAL 1 DAY,'كيس إسمنت تالف'),
(2,2,4,2,'return',5,27500,1,1,137500,CURDATE() - INTERVAL 1 DAY,'مرتجع حديد');

INSERT INTO damaged_goods (warehouse_id, material_id, material_type_id, unit_id, quantity, reason, value_local, damage_date, movement_id) VALUES
(1,1,6,1,2,'كيس إسمنت تالف',9000,CURDATE() - INTERVAL 1 DAY,4);

-- قيد مدين تجريبي (ذمة مدينة غير محصلة) وقيد دائن تجريبي (يُخصم من الميزانية فوراً)
INSERT INTO accounts (project_id, name, acc_type, party_type, collected, description) VALUES
(1,'مدين: شركة المقاولات الفرعية','debtor','other',0,'مبلغ مستحق على مقاول فرعي'),
(1,'دائن: مؤسسة الصلب التجارية','creditor','supplier',0,'التزام مستحق لمورد الحديد');

INSERT INTO account_entries (account_id, project_id, direction, amount, currency_id, exchange_rate, amount_local, ref_type, note, entry_date) VALUES
(6,1,'credit',500000,1,1,500000,'creditor','قيد دائن - يُخصم من ميزانية المشروع',CURDATE() - INTERVAL 2 DAY),
(7,1,'debit',350000,1,1,350000,'creditor','قيد دائن - يُخصم من ميزانية المشروع',CURDATE() - INTERVAL 2 DAY);

-- على الحساب الرئيسي للمشروع الأول: خصم مبلغ الدائن فوراً
INSERT INTO account_entries (account_id, project_id, direction, amount, currency_id, exchange_rate, amount_local, ref_type, note, entry_date) VALUES
(3,1,'debit',500000,1,1,500000,'creditor','خصم مباشر من ميزانية المشروع (دائن)',CURDATE() - INTERVAL 2 DAY);

SET FOREIGN_KEY_CHECKS = 1;
