-- Sales CRM demo dataset for pg-raggraph cookbook (tier: small).
-- Synthetic data; safe to share. See docs/cookbook/sales-crm-ingestion.md.
-- Sample: 200 won + 100 lost deals + dependencies.
-- Generated 2026-04-30.

BEGIN;
CREATE SCHEMA IF NOT EXISTS sales_demo_app;

--
-- PostgreSQL database dump
--


-- Dumped from database version 18.2 (Ubuntu 18.2-1.pgdg25.10+1)
-- Dumped by pg_dump version 18.2 (Ubuntu 18.2-1.pgdg25.10+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_table_access_method = heap;

--
-- Name: customers; Type: TABLE; Schema: sales_demo_app; Owner: -
--

CREATE TABLE sales_demo_app.customers (
    customer_id integer NOT NULL,
    company_name text NOT NULL,
    contact_name text,
    email text,
    phone text,
    industry text,
    created_at timestamp without time zone DEFAULT now(),
    metadata jsonb,
    domain text,
    hq_city text,
    hq_state text,
    hq_state_abbr text,
    hq_country text DEFAULT 'USA'::text
);


--
-- Name: customers_customer_id_seq; Type: SEQUENCE; Schema: sales_demo_app; Owner: -
--

CREATE SEQUENCE sales_demo_app.customers_customer_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: customers_customer_id_seq; Type: SEQUENCE OWNED BY; Schema: sales_demo_app; Owner: -
--

ALTER SEQUENCE sales_demo_app.customers_customer_id_seq OWNED BY sales_demo_app.customers.customer_id;


--
-- Name: products; Type: TABLE; Schema: sales_demo_app; Owner: -
--

CREATE TABLE sales_demo_app.products (
    product_id integer NOT NULL,
    product_name text NOT NULL,
    category text,
    description text,
    base_price numeric(10,2),
    created_at timestamp without time zone DEFAULT now(),
    is_core boolean DEFAULT false
);


--
-- Name: products_product_id_seq; Type: SEQUENCE; Schema: sales_demo_app; Owner: -
--

CREATE SEQUENCE sales_demo_app.products_product_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: products_product_id_seq; Type: SEQUENCE OWNED BY; Schema: sales_demo_app; Owner: -
--

ALTER SEQUENCE sales_demo_app.products_product_id_seq OWNED BY sales_demo_app.products.product_id;


--
-- Name: sales_notes; Type: TABLE; Schema: sales_demo_app; Owner: -
--

CREATE TABLE sales_demo_app.sales_notes (
    note_id integer NOT NULL,
    order_id integer,
    salesperson_id integer,
    note_text text NOT NULL,
    note_type text,
    created_at timestamp without time zone DEFAULT now(),
    use_case_mentioned text[],
    note_text_tsv tsvector,
    sentiment character varying(20),
    product_name character varying(255),
    use_case text
);


--
-- Name: sales_notes_note_id_seq; Type: SEQUENCE; Schema: sales_demo_app; Owner: -
--

CREATE SEQUENCE sales_demo_app.sales_notes_note_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sales_notes_note_id_seq; Type: SEQUENCE OWNED BY; Schema: sales_demo_app; Owner: -
--

ALTER SEQUENCE sales_demo_app.sales_notes_note_id_seq OWNED BY sales_demo_app.sales_notes.note_id;


--
-- Name: sales_orders; Type: TABLE; Schema: sales_demo_app; Owner: -
--

CREATE TABLE sales_demo_app.sales_orders (
    order_id integer NOT NULL,
    customer_id integer,
    salesperson_id integer,
    order_date timestamp without time zone DEFAULT now(),
    status text NOT NULL,
    total_value numeric(12,2),
    expected_close_date date,
    actual_close_date date,
    lost_reason text,
    metadata jsonb,
    win_reason text,
    forecast_confidence text,
    confidence_pct integer,
    inserted_at timestamp without time zone DEFAULT now(),
    qty integer DEFAULT 1,
    product_id integer
);


--
-- Name: COLUMN sales_orders.product_id; Type: COMMENT; Schema: sales_demo_app; Owner: -
--

COMMENT ON COLUMN sales_demo_app.sales_orders.product_id IS 'Product associated with this sales order';


--
-- Name: sales_orders_order_id_seq; Type: SEQUENCE; Schema: sales_demo_app; Owner: -
--

CREATE SEQUENCE sales_demo_app.sales_orders_order_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sales_orders_order_id_seq; Type: SEQUENCE OWNED BY; Schema: sales_demo_app; Owner: -
--

ALTER SEQUENCE sales_demo_app.sales_orders_order_id_seq OWNED BY sales_demo_app.sales_orders.order_id;


--
-- Name: salespeople; Type: TABLE; Schema: sales_demo_app; Owner: -
--

CREATE TABLE sales_demo_app.salespeople (
    salesperson_id integer NOT NULL,
    name text NOT NULL,
    email text NOT NULL,
    region text,
    hire_date date,
    metadata jsonb
);


--
-- Name: salespeople_salesperson_id_seq; Type: SEQUENCE; Schema: sales_demo_app; Owner: -
--

CREATE SEQUENCE sales_demo_app.salespeople_salesperson_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: salespeople_salesperson_id_seq; Type: SEQUENCE OWNED BY; Schema: sales_demo_app; Owner: -
--

ALTER SEQUENCE sales_demo_app.salespeople_salesperson_id_seq OWNED BY sales_demo_app.salespeople.salesperson_id;


--
-- Name: customers customer_id; Type: DEFAULT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.customers ALTER COLUMN customer_id SET DEFAULT nextval('sales_demo_app.customers_customer_id_seq'::regclass);


--
-- Name: products product_id; Type: DEFAULT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.products ALTER COLUMN product_id SET DEFAULT nextval('sales_demo_app.products_product_id_seq'::regclass);


--
-- Name: sales_notes note_id; Type: DEFAULT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.sales_notes ALTER COLUMN note_id SET DEFAULT nextval('sales_demo_app.sales_notes_note_id_seq'::regclass);


--
-- Name: sales_orders order_id; Type: DEFAULT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.sales_orders ALTER COLUMN order_id SET DEFAULT nextval('sales_demo_app.sales_orders_order_id_seq'::regclass);


--
-- Name: salespeople salesperson_id; Type: DEFAULT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.salespeople ALTER COLUMN salesperson_id SET DEFAULT nextval('sales_demo_app.salespeople_salesperson_id_seq'::regclass);


--
-- Name: customers customers_pkey; Type: CONSTRAINT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (customer_id);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (product_id);


--
-- Name: sales_notes sales_notes_pkey; Type: CONSTRAINT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.sales_notes
    ADD CONSTRAINT sales_notes_pkey PRIMARY KEY (note_id);


--
-- Name: sales_orders sales_orders_pkey; Type: CONSTRAINT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.sales_orders
    ADD CONSTRAINT sales_orders_pkey PRIMARY KEY (order_id);


--
-- Name: salespeople salespeople_email_key; Type: CONSTRAINT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.salespeople
    ADD CONSTRAINT salespeople_email_key UNIQUE (email);


--
-- Name: salespeople salespeople_pkey; Type: CONSTRAINT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.salespeople
    ADD CONSTRAINT salespeople_pkey PRIMARY KEY (salesperson_id);


--
-- Name: idx_customers_company; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_customers_company ON sales_demo_app.customers USING btree (company_name);


--
-- Name: idx_customers_hq_country; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_customers_hq_country ON sales_demo_app.customers USING btree (hq_country);


--
-- Name: idx_customers_hq_state; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_customers_hq_state ON sales_demo_app.customers USING btree (hq_state);


--
-- Name: idx_customers_industry; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_customers_industry ON sales_demo_app.customers USING btree (industry);


--
-- Name: idx_notes_created; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_notes_created ON sales_demo_app.sales_notes USING btree (created_at DESC);


--
-- Name: idx_notes_order; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_notes_order ON sales_demo_app.sales_notes USING btree (order_id);


--
-- Name: idx_notes_text_search; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_notes_text_search ON sales_demo_app.sales_notes USING gin (to_tsvector('english'::regconfig, note_text));


--
-- Name: idx_notes_tsv; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_notes_tsv ON sales_demo_app.sales_notes USING gin (note_text_tsv);


--
-- Name: idx_notes_use_case; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_notes_use_case ON sales_demo_app.sales_notes USING gin (use_case_mentioned);


--
-- Name: idx_orders_customer; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_orders_customer ON sales_demo_app.sales_orders USING btree (customer_id);


--
-- Name: idx_orders_date; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_orders_date ON sales_demo_app.sales_orders USING btree (order_date DESC);


--
-- Name: idx_orders_inserted; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_orders_inserted ON sales_demo_app.sales_orders USING btree (inserted_at DESC);


--
-- Name: idx_orders_salesperson; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_orders_salesperson ON sales_demo_app.sales_orders USING btree (salesperson_id);


--
-- Name: idx_orders_status; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_orders_status ON sales_demo_app.sales_orders USING btree (status);


--
-- Name: idx_products_category; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_products_category ON sales_demo_app.products USING btree (category);


--
-- Name: idx_products_is_core; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_products_is_core ON sales_demo_app.products USING btree (is_core);


--
-- Name: idx_products_name; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_products_name ON sales_demo_app.products USING btree (product_name);


--
-- Name: idx_sales_notes_sentiment; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_sales_notes_sentiment ON sales_demo_app.sales_notes USING btree (sentiment);


--
-- Name: idx_sales_orders_product; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_sales_orders_product ON sales_demo_app.sales_orders USING btree (product_id);


--
-- Name: idx_sales_orders_qty; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_sales_orders_qty ON sales_demo_app.sales_orders USING btree (qty);


--
-- Name: idx_salespeople_name; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_salespeople_name ON sales_demo_app.salespeople USING btree (name);


--
-- Name: idx_salespeople_region; Type: INDEX; Schema: sales_demo_app; Owner: -
--

CREATE INDEX idx_salespeople_region ON sales_demo_app.salespeople USING btree (region);


--
-- Name: sales_orders sales_orders_track_changes; Type: TRIGGER; Schema: sales_demo_app; Owner: -
--



--
-- Name: sales_notes trg_sales_notes_tsv; Type: TRIGGER; Schema: sales_demo_app; Owner: -
--



--
-- Name: sales_orders update_customer_products; Type: TRIGGER; Schema: sales_demo_app; Owner: -
--



--
-- Name: sales_notes sales_notes_order_id_fkey; Type: FK CONSTRAINT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.sales_notes
    ADD CONSTRAINT sales_notes_order_id_fkey FOREIGN KEY (order_id) REFERENCES sales_demo_app.sales_orders(order_id);


--
-- Name: sales_notes sales_notes_salesperson_id_fkey; Type: FK CONSTRAINT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.sales_notes
    ADD CONSTRAINT sales_notes_salesperson_id_fkey FOREIGN KEY (salesperson_id) REFERENCES sales_demo_app.salespeople(salesperson_id);


--
-- Name: sales_orders sales_orders_customer_id_fkey; Type: FK CONSTRAINT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.sales_orders
    ADD CONSTRAINT sales_orders_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES sales_demo_app.customers(customer_id);


--
-- Name: sales_orders sales_orders_product_id_fkey; Type: FK CONSTRAINT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.sales_orders
    ADD CONSTRAINT sales_orders_product_id_fkey FOREIGN KEY (product_id) REFERENCES sales_demo_app.products(product_id) ON DELETE SET NULL;


--
-- Name: sales_orders sales_orders_salesperson_id_fkey; Type: FK CONSTRAINT; Schema: sales_demo_app; Owner: -
--

ALTER TABLE ONLY sales_demo_app.sales_orders
    ADD CONSTRAINT sales_orders_salesperson_id_fkey FOREIGN KEY (salesperson_id) REFERENCES sales_demo_app.salespeople(salesperson_id);


--
-- PostgreSQL database dump complete
--

-- Data (dependency order: salespeople, customers, products → orders → notes).

-- salespeople: 46 rows
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (1, 'Ava Chen', 'ava.chen@yonk.example', 'West', '2023-02-21', '{"seed_key": "sp-ava-chen", "demo_seed": true}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (2, 'Liam Park', 'liam.park@yonk.example', 'Central', '2024-02-21', '{"seed_key": "sp-liam-park", "demo_seed": true}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (3, 'Michael Chen', 'michael.chen@company.com', 'APAC', '2019-06-10', '{"level": "senior", "quota": 600000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (4, 'Emily Rodriguez', 'emily.rodriguez@company.com', 'LATAM', '2021-08-05', '{"level": "mid", "quota": 350000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (5, 'David Kim', 'david.kim@company.com', 'APAC', '2022-01-12', '{"level": "junior", "quota": 300000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (6, 'Lisa Anderson', 'lisa.anderson@company.com', 'Europe', '2020-11-03', '{"level": "senior", "quota": 450000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (7, 'James Wilson', 'james.wilson@company.com', 'North America', '2021-05-18', '{"level": "mid", "quota": 380000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (8, 'Maria Garcia', 'maria.garcia@company.com', 'LATAM', '2020-09-25', '{"level": "senior", "quota": 420000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (9, 'Robert Taylor', 'robert.taylor@company.com', 'Europe', '2022-02-14', '{"level": "junior", "quota": 320000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (10, 'Jennifer Lee', 'jennifer.lee@company.com', 'APAC', '2019-12-08', '{"level": "senior", "quota": 550000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (11, 'Sales Rep 11', 'sales11@company.com', 'LATAM', '2024-11-28', '{"level": "mid", "quota": 410000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (12, 'Sales Rep 12', 'sales12@company.com', 'North America', '2024-10-29', '{"level": "mid", "quota": 420000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (13, 'Sales Rep 13', 'sales13@company.com', 'Europe', '2024-09-29', '{"level": "mid", "quota": 430000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (15, 'Sales Rep 15', 'sales15@company.com', 'LATAM', '2024-07-31', '{"level": "mid", "quota": 450000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (16, 'Sales Rep 16', 'sales16@company.com', 'North America', '2024-07-01', '{"level": "mid", "quota": 460000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (17, 'Sales Rep 17', 'sales17@company.com', 'Europe', '2024-06-01', '{"level": "mid", "quota": 470000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (18, 'Sales Rep 18', 'sales18@company.com', 'APAC', '2024-05-02', '{"level": "mid", "quota": 480000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (19, 'Sales Rep 19', 'sales19@company.com', 'LATAM', '2024-04-02', '{"level": "mid", "quota": 490000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (20, 'Sales Rep 20', 'sales20@company.com', 'North America', '2024-03-03', '{"level": "mid", "quota": 500000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (22, 'Sales Rep 22', 'sales22@company.com', 'APAC', '2024-01-03', '{"level": "mid", "quota": 520000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (23, 'Sales Rep 23', 'sales23@company.com', 'LATAM', '2023-12-04', '{"level": "mid", "quota": 530000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (24, 'Sales Rep 24', 'sales24@company.com', 'North America', '2023-11-04', '{"level": "mid", "quota": 540000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (25, 'Sales Rep 25', 'sales25@company.com', 'Europe', '2023-10-05', '{"level": "mid", "quota": 550000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (26, 'Sales Rep 26', 'sales26@company.com', 'APAC', '2023-09-05', '{"level": "mid", "quota": 560000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (27, 'Sales Rep 27', 'sales27@company.com', 'LATAM', '2023-08-06', '{"level": "mid", "quota": 570000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (28, 'Sales Rep 28', 'sales28@company.com', 'North America', '2023-07-07', '{"level": "mid", "quota": 580000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (29, 'Sales Rep 29', 'sales29@company.com', 'Europe', '2023-06-07', '{"level": "mid", "quota": 590000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (31, 'Sales Rep 31', 'sales31@company.com', 'LATAM', '2023-04-08', '{"level": "mid", "quota": 610000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (32, 'Sales Rep 32', 'sales32@company.com', 'North America', '2023-03-09', '{"level": "mid", "quota": 620000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (33, 'Sales Rep 33', 'sales33@company.com', 'Europe', '2023-02-07', '{"level": "mid", "quota": 630000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (34, 'Sales Rep 34', 'sales34@company.com', 'APAC', '2023-01-08', '{"level": "mid", "quota": 640000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (35, 'Sales Rep 35', 'sales35@company.com', 'LATAM', '2022-12-09', '{"level": "mid", "quota": 650000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (37, 'Sales Rep 37', 'sales37@company.com', 'Europe', '2022-10-10', '{"level": "mid", "quota": 670000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (38, 'Sales Rep 38', 'sales38@company.com', 'APAC', '2022-09-10', '{"level": "mid", "quota": 680000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (39, 'Sales Rep 39', 'sales39@company.com', 'LATAM', '2022-08-11', '{"level": "mid", "quota": 690000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (40, 'Sales Rep 40', 'sales40@company.com', 'North America', '2022-07-12', '{"level": "mid", "quota": 700000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (41, 'Sales Rep 41', 'sales41@company.com', 'Europe', '2022-06-12', '{"level": "mid", "quota": 710000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (42, 'Sales Rep 42', 'sales42@company.com', 'APAC', '2022-05-13', '{"level": "mid", "quota": 720000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (43, 'Sales Rep 43', 'sales43@company.com', 'LATAM', '2022-04-13', '{"level": "mid", "quota": 730000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (44, 'Sales Rep 44', 'sales44@company.com', 'North America', '2022-03-14', '{"level": "mid", "quota": 740000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (45, 'Sales Rep 45', 'sales45@company.com', 'Europe', '2022-02-12', '{"level": "mid", "quota": 750000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (46, 'Sales Rep 46', 'sales46@company.com', 'APAC', '2022-01-13', '{"level": "mid", "quota": 760000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (47, 'Sales Rep 47', 'sales47@company.com', 'LATAM', '2021-12-14', '{"level": "mid", "quota": 770000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (48, 'Sales Rep 48', 'sales48@company.com', 'North America', '2021-11-14', '{"level": "mid", "quota": 780000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (49, 'Sales Rep 49', 'sales49@company.com', 'Europe', '2021-10-15', '{"level": "mid", "quota": 790000}'::jsonb);
INSERT INTO sales_demo_app.salespeople (salesperson_id, name, email, region, hire_date, metadata) VALUES (50, 'Sales Rep 50', 'sales50@company.com', 'APAC', '2021-09-15', '{"level": "mid", "quota": 800000}'::jsonb);


-- customers: 254 rows
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1, 'Insightful Strategy Group', 'Dana Holtz', 'dana.holtz@insightfulstrategy.com', '555-201-1188', 'Consulting', '2026-02-21T18:11:22.129076', '{"seed_key": "customer-isg", "demo_seed": true}'::jsonb, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (3, 'Jones Technology Systems', 'Lisa Garcia', 'Michael.Jones@Jon.com', NULL, 'Education', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (7, 'Jones Healthcare Solutions', 'Jane Davis', 'John.Smith@Jon.com', NULL, 'Healthcare', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (8, 'Miller Healthcare Solutions', 'Emily Williams', 'Michael.Williams@Mil.com', NULL, 'Healthcare', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (9, 'Miller Retail Co', 'Sarah Johnson', 'Jane.Smith@Mil.com', NULL, 'Retail', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (10, 'Smith Manufacturing Inc', 'Sarah Smith', 'Michael.Jones@Smi.com', NULL, 'Manufacturing', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (17, 'Williams Healthcare Solutions', 'Sarah Miller', 'John.Smith@Wil.com', NULL, 'Manufacturing', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (19, 'Jones Finance Corp', 'Michael Smith', 'David.Williams@Jon.com', NULL, 'Retail', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (20, 'Johnson Education LLC', 'David Davis', 'John.Garcia@Joh.com', NULL, 'Retail', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (22, 'Miller Healthcare Corp', 'Sarah Smith', 'Jane.Garcia@Mil.com', NULL, 'Technology', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (23, 'Brown Technology Co', 'John Johnson', 'Jane.Jones@Bro.com', NULL, 'Healthcare', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (24, 'Brown Education LLC', 'David Williams', 'Michael.Johnson@Bro.com', NULL, 'Finance', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (26, 'Garcia Education Ltd', 'Emily Garcia', 'Sarah.Jones@Gar.com', NULL, 'Manufacturing', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (28, 'Davis Retail Co', 'Lisa Davis', 'David.Williams@Dav.com', NULL, 'Education', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (32, 'Smith Education Inc', 'David Davis', 'Emily.Miller@Smi.com', NULL, 'Healthcare', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (33, 'Garcia Technology Solutions', 'Michael Johnson', 'Jane.Smith@Gar.com', NULL, 'Education', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (34, 'Williams Technology Systems', 'Robert Brown', 'Michael.Miller@Wil.com', NULL, 'Finance', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (40, 'Smith Education Solutions', 'Michael Smith', 'Sarah.Williams@Smi.com', NULL, 'Education', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (41, 'Smith Healthcare Group', 'Sarah Johnson', 'John.Miller@Smi.com', NULL, 'Technology', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (49, 'Johnson Technology Systems', 'Robert Smith', 'Michael.Williams@Joh.com', NULL, 'Healthcare', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (51, 'Garcia Healthcare Inc', 'Robert Garcia', 'Emily.Garcia@Gar.com', NULL, 'Retail', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (54, 'Davis Healthcare Systems', 'David Garcia', 'Michael.Brown@Dav.com', NULL, 'Retail', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (59, 'Williams Retail Corp', 'Jane Miller', 'Emily.Williams@Wil.com', NULL, 'Technology', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (63, 'Davis Retail Group', 'Emily Davis', 'David.Davis@Dav.com', NULL, 'Finance', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (65, 'Johnson Finance LLC', 'Jane Davis', 'David.Smith@Joh.com', NULL, 'Finance', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (66, 'Johnson Retail Group', 'John Johnson', 'Jane.Davis@Joh.com', NULL, 'Technology', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (72, 'Williams Retail Corp', 'Emily Brown', 'John.Johnson@Wil.com', NULL, 'Technology', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (73, 'Davis Retail Inc', 'Lisa Brown', 'David.Brown@Dav.com', NULL, 'Finance', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (75, 'Williams Healthcare Corp', 'David Williams', 'Sarah.Jones@Wil.com', NULL, 'Healthcare', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (77, 'Jones Technology Corp', 'Emily Smith', 'David.Jones@Jon.com', NULL, 'Retail', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (79, 'Williams Retail Ltd', 'Emily Johnson', 'Lisa.Miller@Wil.com', NULL, 'Finance', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (85, 'Garcia Finance LLC', 'David Miller', 'Michael.Williams@Gar.com', NULL, 'Education', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (86, 'Williams Technology Corp', 'Jane Johnson', 'Sarah.Smith@Wil.com', NULL, 'Technology', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (90, 'Johnson Manufacturing Solutions', 'Jane Johnson', 'Emily.Williams@Joh.com', NULL, 'Manufacturing', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (92, 'Jones Healthcare Inc', 'Michael Jones', 'Lisa.Smith@Jon.com', NULL, 'Education', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (93, 'Garcia Retail Inc', 'Lisa Miller', 'Michael.Miller@Gar.com', NULL, 'Manufacturing', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (94, 'Davis Technology Group', 'Michael Brown', 'Sarah.Smith@Dav.com', NULL, 'Education', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (97, 'Brown Technology Ltd', 'Emily Brown', 'Emily.Jones@Bro.com', NULL, 'Finance', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (98, 'Smith Retail Inc', 'Emily Williams', 'Robert.Garcia@Smi.com', NULL, 'Manufacturing', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (99, 'Miller Education Solutions', 'David Smith', 'John.Brown@Mil.com', NULL, 'Education', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (100, 'Davis Retail Ltd', 'David Brown', 'Sarah.Williams@Dav.com', NULL, 'Technology', '2026-02-21T18:11:55.854203', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (105, 'Miller Retail Systems', 'Michael Miller', 'Lisa.Johnson@Mil.com', NULL, 'Manufacturing', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (109, 'Garcia Finance LLC', 'Robert Garcia', 'Sarah.Garcia@Gar.com', NULL, 'Manufacturing', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (112, 'Brown Technology Corp', 'David Jones', 'Lisa.Johnson@Bro.com', NULL, 'Healthcare', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (117, 'Johnson Education Ltd', 'Lisa Smith', 'John.Williams@Joh.com', NULL, 'Education', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (118, 'Davis Technology Solutions', 'Jane Davis', 'Michael.Miller@Dav.com', NULL, 'Healthcare', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (120, 'Johnson Manufacturing Systems', 'Sarah Davis', 'David.Davis@Joh.com', NULL, 'Healthcare', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (121, 'Johnson Education LLC', 'Robert Jones', 'Robert.Davis@Joh.com', NULL, 'Retail', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (122, 'Garcia Healthcare Group', 'Lisa Brown', 'Lisa.Miller@Gar.com', NULL, 'Education', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (123, 'Davis Education Inc', 'David Brown', 'Emily.Miller@Dav.com', NULL, 'Manufacturing', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (126, 'Williams Manufacturing Inc', 'David Williams', 'Emily.Jones@Wil.com', NULL, 'Manufacturing', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (127, 'Miller Retail Co', 'Emily Brown', 'Robert.Smith@Mil.com', NULL, 'Retail', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (128, 'Smith Education Group', 'Emily Johnson', 'Emily.Davis@Smi.com', NULL, 'Technology', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (129, 'Garcia Retail Systems', 'Emily Brown', 'Robert.Miller@Gar.com', NULL, 'Manufacturing', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (136, 'Garcia Education Co', 'Sarah Smith', 'David.Williams@Gar.com', NULL, 'Finance', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (138, 'Johnson Finance Solutions', 'Sarah Miller', 'Robert.Smith@Joh.com', NULL, 'Healthcare', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (141, 'Brown Technology Ltd', 'Michael Smith', 'Emily.Garcia@Bro.com', NULL, 'Education', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (142, 'Williams Healthcare Systems', 'Sarah Williams', 'Emily.Jones@Wil.com', NULL, 'Finance', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (145, 'Davis Healthcare Group', 'Emily Miller', 'Lisa.Miller@Dav.com', NULL, 'Finance', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (148, 'Williams Technology Co', 'Lisa Williams', 'John.Brown@Wil.com', NULL, 'Healthcare', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (150, 'Smith Retail Co', 'Sarah Johnson', 'Michael.Smith@Smi.com', NULL, 'Healthcare', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (151, 'Brown Healthcare Solutions', 'Sarah Garcia', 'Emily.Williams@Bro.com', NULL, 'Healthcare', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (153, 'Johnson Manufacturing Inc', 'Michael Davis', 'John.Miller@Joh.com', NULL, 'Education', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (155, 'Jones Retail Solutions', 'Robert Miller', 'Michael.Smith@Jon.com', NULL, 'Finance', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (157, 'Brown Finance Group', 'David Brown', 'Lisa.Miller@Bro.com', NULL, 'Technology', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (161, 'Johnson Education Group', 'Lisa Jones', 'Emily.Brown@Joh.com', NULL, 'Retail', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (162, 'Williams Manufacturing Corp', 'Lisa Johnson', 'Sarah.Davis@Wil.com', NULL, 'Finance', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (163, 'Johnson Manufacturing Systems', 'Michael Brown', 'Emily.Garcia@Joh.com', NULL, 'Manufacturing', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (170, 'Davis Healthcare Inc', 'Michael Smith', 'Michael.Williams@Dav.com', NULL, 'Retail', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (175, 'Smith Technology Group', 'Jane Garcia', 'Lisa.Jones@Smi.com', NULL, 'Retail', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (180, 'Jones Technology Solutions', 'Jane Davis', 'Emily.Johnson@Jon.com', NULL, 'Finance', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (187, 'Jones Manufacturing Group', 'Sarah Davis', 'Emily.Garcia@Jon.com', NULL, 'Manufacturing', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (190, 'Jones Healthcare Inc', 'Michael Jones', 'Michael.Johnson@Jon.com', NULL, 'Manufacturing', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (192, 'Williams Manufacturing Ltd', 'Emily Miller', 'John.Brown@Wil.com', NULL, 'Healthcare', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (193, 'Johnson Finance Co', 'Lisa Smith', 'Robert.Williams@Joh.com', NULL, 'Technology', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (194, 'Davis Manufacturing Solutions', 'Lisa Johnson', 'Sarah.Brown@Dav.com', NULL, 'Healthcare', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (197, 'Smith Retail LLC', 'Emily Jones', 'David.Johnson@Smi.com', NULL, 'Technology', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (199, 'Williams Manufacturing Inc', 'Jane Johnson', 'Jane.Jones@Wil.com', NULL, 'Healthcare', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (202, 'Smith Technology Systems', 'Michael Jones', 'Lisa.Johnson@Smi.com', NULL, 'Finance', '2026-02-21T18:11:58.398206', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (208, 'Williams Finance Corp', 'John Smith', 'Sarah.Smith@Wil.com', NULL, 'Healthcare', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (214, 'Davis Manufacturing Systems', 'Sarah Smith', 'David.Smith@Dav.com', NULL, 'Retail', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (216, 'Garcia Healthcare Group', 'Robert Davis', 'Lisa.Brown@Gar.com', NULL, 'Finance', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (225, 'Johnson Finance LLC', 'John Williams', 'Michael.Johnson@Joh.com', NULL, 'Retail', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (226, 'Jones Education Group', 'Robert Williams', 'Sarah.Davis@Jon.com', NULL, 'Retail', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (227, 'Davis Retail Corp', 'Sarah Garcia', 'David.Miller@Dav.com', NULL, 'Retail', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (228, 'Davis Technology Ltd', 'Robert Brown', 'Robert.Brown@Dav.com', NULL, 'Finance', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (229, 'Jones Manufacturing Systems', 'Sarah Miller', 'Emily.Davis@Jon.com', NULL, 'Finance', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (231, 'Davis Education Corp', 'David Jones', 'Lisa.Jones@Dav.com', NULL, 'Retail', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (234, 'Miller Manufacturing Co', 'Lisa Miller', 'Lisa.Davis@Mil.com', NULL, 'Retail', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (237, 'Brown Education Co', 'David Jones', 'Lisa.Brown@Bro.com', NULL, 'Retail', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (238, 'Garcia Manufacturing Systems', 'Lisa Miller', 'David.Williams@Gar.com', NULL, 'Education', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (248, 'Brown Technology LLC', 'Michael Miller', 'Jane.Smith@Bro.com', NULL, 'Technology', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (251, 'Jones Finance Corp', 'Robert Miller', 'John.Williams@Jon.com', NULL, 'Technology', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (252, 'Johnson Healthcare Group', 'Lisa Williams', 'Robert.Jones@Joh.com', NULL, 'Manufacturing', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (258, 'Brown Finance Ltd', 'Michael Davis', 'Jane.Jones@Bro.com', NULL, 'Technology', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (259, 'Miller Technology Ltd', 'Robert Miller', 'Jane.Brown@Mil.com', NULL, 'Healthcare', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (261, 'Johnson Technology Co', 'John Smith', 'John.Smith@Joh.com', NULL, 'Technology', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (262, 'Smith Finance Solutions', 'John Brown', 'Sarah.Williams@Smi.com', NULL, 'Technology', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (265, 'Johnson Finance Solutions', 'Robert Smith', 'David.Smith@Joh.com', NULL, 'Retail', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (272, 'Miller Finance Inc', 'Lisa Jones', 'Sarah.Williams@Mil.com', NULL, 'Finance', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (273, 'Williams Retail Systems', 'Sarah Miller', 'David.Brown@Wil.com', NULL, 'Education', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (274, 'Williams Retail Systems', 'Sarah Davis', 'Sarah.Garcia@Wil.com', NULL, 'Retail', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (276, 'Miller Healthcare Ltd', 'Emily Brown', 'Sarah.Smith@Mil.com', NULL, 'Retail', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (277, 'Smith Healthcare Systems', 'Lisa Davis', 'John.Miller@Smi.com', NULL, 'Technology', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (279, 'Jones Finance Inc', 'John Miller', 'David.Brown@Jon.com', NULL, 'Finance', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (280, 'Brown Education Solutions', 'Jane Johnson', 'Sarah.Johnson@Bro.com', NULL, 'Retail', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (282, 'Smith Manufacturing Group', 'Sarah Jones', 'Sarah.Jones@Smi.com', NULL, 'Manufacturing', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (283, 'Garcia Finance Group', 'Lisa Garcia', 'Michael.Brown@Gar.com', NULL, 'Technology', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (287, 'Smith Technology LLC', 'Sarah Davis', 'Lisa.Miller@Smi.com', NULL, 'Finance', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (288, 'Miller Healthcare Solutions', 'Robert Jones', 'Jane.Williams@Mil.com', NULL, 'Healthcare', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (290, 'Miller Manufacturing Ltd', 'Sarah Smith', 'Sarah.Johnson@Mil.com', NULL, 'Technology', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (291, 'Johnson Retail Co', 'Lisa Smith', 'John.Jones@Joh.com', NULL, 'Manufacturing', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (295, 'Garcia Technology Systems', 'David Johnson', 'Lisa.Miller@Gar.com', NULL, 'Finance', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (297, 'Brown Technology Group', 'Emily Smith', 'Emily.Johnson@Bro.com', NULL, 'Education', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (300, 'Williams Retail Solutions', 'Lisa Smith', 'Sarah.Jones@Wil.com', NULL, 'Technology', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (302, 'Jones Retail Inc', 'Emily Jones', 'David.Johnson@Jon.com', NULL, 'Finance', '2026-02-21T18:12:01.981802', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (311, 'Brown Retail Ltd', 'Emily Garcia', 'Michael.Miller@Bro.com', NULL, 'Technology', '2026-02-21T18:37:34.906855', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (327, 'Williams Education Group', 'David Davis', 'David.Smith@Wil.com', NULL, 'Retail', '2026-02-21T18:37:34.906855', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (341, 'Williams Retail Group', 'Jane Johnson', 'David.Johnson@Wil.com', NULL, 'Healthcare', '2026-02-21T18:37:34.906855', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (342, 'Brown Healthcare Ltd', 'Jane Williams', 'Emily.Smith@Bro.com', NULL, 'Manufacturing', '2026-02-21T18:37:34.906855', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (350, 'Jones Education LLC', 'Emily Jones', 'John.Garcia@Jon.com', NULL, 'Technology', '2026-02-21T18:37:34.906855', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (359, 'Davis Healthcare Solutions', 'Michael Miller', 'Emily.Williams@Dav.com', NULL, 'Technology', '2026-02-21T18:37:34.906855', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (365, 'Miller Education Inc', 'Emily Williams', 'Lisa.Miller@Mil.com', NULL, 'Technology', '2026-02-21T18:37:34.906855', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (387, 'Garcia Healthcare Solutions', 'Lisa Miller', 'John.Johnson@Gar.com', NULL, 'Healthcare', '2026-02-21T18:37:34.906855', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (393, 'Smith Healthcare Solutions', 'David Johnson', 'Sarah.Williams@Smi.com', NULL, 'Manufacturing', '2026-02-21T18:37:34.906855', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (402, 'Johnson Manufacturing Ltd', 'Sarah Garcia', 'Michael.Miller@Joh.com', NULL, 'Technology', '2026-02-21T18:37:34.906855', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (413, 'Johnson Finance Inc', 'John Johnson', 'Robert.Jones@Joh.com', NULL, 'Education', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (414, 'Brown Technology Corp', 'Robert Brown', 'David.Johnson@Bro.com', NULL, 'Healthcare', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (419, 'Garcia Manufacturing Solutions', 'David Smith', 'Sarah.Davis@Gar.com', NULL, 'Healthcare', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (440, 'Miller Finance Co', 'Robert Miller', 'Emily.Garcia@Mil.com', NULL, 'Education', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (445, 'Jones Manufacturing Corp', 'Emily Williams', 'Michael.Miller@Jon.com', NULL, 'Healthcare', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (453, 'Davis Manufacturing Inc', 'Sarah Johnson', 'Emily.Miller@Dav.com', NULL, 'Finance', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (458, 'Brown Healthcare Solutions', 'Sarah Smith', 'Jane.Smith@Bro.com', NULL, 'Finance', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (468, 'Garcia Retail Inc', 'Robert Johnson', 'David.Miller@Gar.com', NULL, 'Finance', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (474, 'Williams Healthcare Inc', 'Robert Jones', 'Sarah.Brown@Wil.com', NULL, 'Education', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (478, 'Williams Healthcare Corp', 'Jane Brown', 'David.Davis@Wil.com', NULL, 'Education', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (479, 'Brown Technology Inc', 'Michael Jones', 'Sarah.Brown@Bro.com', NULL, 'Education', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (480, 'Williams Retail Co', 'Lisa Garcia', 'Emily.Brown@Wil.com', NULL, 'Education', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (484, 'Jones Technology Corp', 'Jane Davis', 'Michael.Jones@Jon.com', NULL, 'Education', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (485, 'Smith Retail Solutions', 'Lisa Davis', 'David.Williams@Smi.com', NULL, 'Healthcare', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (487, 'Garcia Finance Systems', 'John Garcia', 'David.Miller@Gar.com', NULL, 'Manufacturing', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (488, 'Garcia Finance Corp', 'David Smith', 'Sarah.Smith@Gar.com', NULL, 'Manufacturing', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (495, 'Miller Healthcare Ltd', 'Emily Smith', 'David.Johnson@Mil.com', NULL, 'Education', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (498, 'Brown Finance Systems', 'Jane Jones', 'Sarah.Garcia@Bro.com', NULL, 'Retail', '2026-02-21T18:37:39.498628', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (510, 'Davis Finance Systems', 'Emily Davis', 'Sarah.Garcia@Dav.com', NULL, 'Retail', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (521, 'Garcia Technology Systems', 'John Miller', 'Lisa.Smith@Gar.com', NULL, 'Technology', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (523, 'Jones Education Ltd', 'David Williams', 'Robert.Garcia@Jon.com', NULL, 'Technology', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (524, 'Brown Education Co', 'Michael Williams', 'Michael.Johnson@Bro.com', NULL, 'Education', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (525, 'Garcia Manufacturing Corp', 'Sarah Miller', 'Robert.Smith@Gar.com', NULL, 'Healthcare', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (529, 'Williams Finance Co', 'Robert Jones', 'Emily.Jones@Wil.com', NULL, 'Education', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (531, 'Garcia Manufacturing Co', 'Emily Miller', 'David.Smith@Gar.com', NULL, 'Education', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (535, 'Johnson Technology Inc', 'Michael Williams', 'David.Jones@Joh.com', NULL, 'Finance', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (548, 'Smith Manufacturing Inc', 'Michael Jones', 'Sarah.Johnson@Smi.com', NULL, 'Manufacturing', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (550, 'Smith Education LLC', 'David Williams', 'Robert.Williams@Smi.com', NULL, 'Healthcare', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (555, 'Garcia Manufacturing Solutions', 'Lisa Miller', 'Jane.Smith@Gar.com', NULL, 'Technology', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (558, 'Smith Retail Corp', 'Robert Jones', 'John.Garcia@Smi.com', NULL, 'Technology', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (564, 'Smith Manufacturing Solutions', 'David Brown', 'Emily.Brown@Smi.com', NULL, 'Healthcare', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (570, 'Smith Technology Systems', 'David Jones', 'David.Williams@Smi.com', NULL, 'Healthcare', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (577, 'Miller Healthcare Solutions', 'Robert Brown', 'Emily.Miller@Mil.com', NULL, 'Retail', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (579, 'Garcia Manufacturing Corp', 'Sarah Jones', 'Jane.Garcia@Gar.com', NULL, 'Healthcare', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (580, 'Miller Education Group', 'Jane Davis', 'Jane.Brown@Mil.com', NULL, 'Manufacturing', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (581, 'Smith Healthcare LLC', 'John Davis', 'Sarah.Johnson@Smi.com', NULL, 'Retail', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (584, 'Davis Education Corp', 'Jane Smith', 'Michael.Davis@Dav.com', NULL, 'Finance', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (598, 'Brown Finance Group', 'Sarah Williams', 'Jane.Smith@Bro.com', NULL, 'Healthcare', '2026-02-21T18:37:43.738767', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (606, 'Miller Finance Corp', 'Sarah Brown', 'Sarah.Smith@Mil.com', NULL, 'Technology', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (634, 'Garcia Finance Corp', 'Lisa Davis', 'John.Davis@Gar.com', NULL, 'Manufacturing', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (635, 'Johnson Education Ltd', 'Robert Davis', 'Lisa.Brown@Joh.com', NULL, 'Technology', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (636, 'Garcia Manufacturing Inc', 'John Williams', 'John.Smith@Gar.com', NULL, 'Finance', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (647, 'Garcia Healthcare Co', 'David Jones', 'Michael.Smith@Gar.com', NULL, 'Healthcare', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (648, 'Johnson Healthcare Ltd', 'John Miller', 'Sarah.Garcia@Joh.com', NULL, 'Technology', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (649, 'Brown Technology Ltd', 'John Davis', 'David.Davis@Bro.com', NULL, 'Finance', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (650, 'Davis Manufacturing Systems', 'Jane Jones', 'Jane.Davis@Dav.com', NULL, 'Retail', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (651, 'Miller Education Inc', 'Emily Brown', 'John.Williams@Mil.com', NULL, 'Retail', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (655, 'Brown Healthcare Solutions', 'John Garcia', 'Sarah.Miller@Bro.com', NULL, 'Healthcare', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (659, 'Johnson Technology Group', 'Lisa Brown', 'Michael.Davis@Joh.com', NULL, 'Education', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (679, 'Williams Healthcare Corp', 'Sarah Brown', 'Emily.Williams@Wil.com', NULL, 'Healthcare', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (690, 'Jones Finance Corp', 'Michael Williams', 'Sarah.Garcia@Jon.com', NULL, 'Education', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (691, 'Garcia Finance Systems', 'Michael Miller', 'John.Brown@Gar.com', NULL, 'Healthcare', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (697, 'Davis Finance Co', 'Lisa Johnson', 'Lisa.Johnson@Dav.com', NULL, 'Education', '2026-04-06T15:26:18.574883', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (710, 'Johnson Manufacturing LLC', 'Emily Jones', 'John.Williams@Joh.com', NULL, 'Retail', '2026-04-06T15:26:42.280102', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (737, 'Garcia Retail Group', 'Lisa Smith', 'Sarah.Johnson@Gar.com', NULL, 'Education', '2026-04-06T15:26:42.280102', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (739, 'Davis Healthcare Corp', 'Robert Smith', 'Lisa.Jones@Dav.com', NULL, 'Finance', '2026-04-06T15:26:42.280102', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (741, 'Jones Retail Solutions', 'Jane Miller', 'Lisa.Williams@Jon.com', NULL, 'Retail', '2026-04-06T15:26:42.280102', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (760, 'Garcia Technology Inc', 'Robert Davis', 'Lisa.Williams@Gar.com', NULL, 'Manufacturing', '2026-04-06T15:26:42.280102', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (773, 'Jones Finance Corp', 'Michael Brown', 'Emily.Jones@Jon.com', NULL, 'Manufacturing', '2026-04-06T15:26:42.280102', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (776, 'Miller Finance LLC', 'Lisa Jones', 'Michael.Garcia@Mil.com', NULL, 'Education', '2026-04-06T15:26:42.280102', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (779, 'Garcia Healthcare LLC', 'John Miller', 'John.Garcia@Gar.com', NULL, 'Technology', '2026-04-06T15:26:42.280102', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (780, 'Johnson Education Co', 'Robert Davis', 'Michael.Jones@Joh.com', NULL, 'Healthcare', '2026-04-06T15:26:42.280102', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (787, 'Johnson Retail Inc', 'Emily Miller', 'Sarah.Garcia@Joh.com', NULL, 'Finance', '2026-04-06T15:26:42.280102', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (800, 'Garcia Healthcare Systems', 'John Smith', 'Sarah.Garcia@Gar.com', NULL, 'Healthcare', '2026-04-06T15:26:42.280102', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (805, 'Johnson Manufacturing Ltd', 'Emily Williams', 'Sarah.Miller@Joh.com', NULL, 'Technology', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (811, 'Williams Education Group', 'John Brown', 'Sarah.Jones@Wil.com', NULL, 'Manufacturing', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (813, 'Williams Finance Corp', 'Emily Williams', 'Jane.Smith@Wil.com', NULL, 'Technology', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (816, 'Davis Retail Group', 'Sarah Davis', 'Emily.Davis@Dav.com', NULL, 'Manufacturing', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (824, 'Davis Education Inc', 'Michael Johnson', 'Lisa.Smith@Dav.com', NULL, 'Education', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (829, 'Jones Finance Ltd', 'John Davis', 'Robert.Jones@Jon.com', NULL, 'Manufacturing', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (831, 'Davis Manufacturing LLC', 'Emily Garcia', 'Emily.Brown@Dav.com', NULL, 'Retail', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (833, 'Jones Healthcare Inc', 'David Brown', 'Sarah.Miller@Jon.com', NULL, 'Manufacturing', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (835, 'Johnson Finance Inc', 'Sarah Jones', 'Jane.Jones@Joh.com', NULL, 'Retail', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (844, 'Johnson Education Inc', 'John Davis', 'Robert.Miller@Joh.com', NULL, 'Finance', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (849, 'Jones Retail Group', 'David Williams', 'Emily.Garcia@Jon.com', NULL, 'Technology', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (856, 'Davis Retail Inc', 'Lisa Williams', 'David.Johnson@Dav.com', NULL, 'Healthcare', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (859, 'Johnson Retail Inc', 'Michael Johnson', 'David.Williams@Joh.com', NULL, 'Manufacturing', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (870, 'Smith Manufacturing Ltd', 'Sarah Johnson', 'Sarah.Brown@Smi.com', NULL, 'Education', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (872, 'Garcia Healthcare Solutions', 'Lisa Brown', 'Lisa.Brown@Gar.com', NULL, 'Manufacturing', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (874, 'Williams Education Solutions', 'John Smith', 'Emily.Johnson@Wil.com', NULL, 'Education', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (877, 'Davis Finance Co', 'Emily Jones', 'Robert.Brown@Dav.com', NULL, 'Retail', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (879, 'Williams Finance Corp', 'Robert Garcia', 'Jane.Garcia@Wil.com', NULL, 'Healthcare', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (887, 'Johnson Healthcare Group', 'John Smith', 'Michael.Miller@Joh.com', NULL, 'Healthcare', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (891, 'Brown Education Corp', 'Sarah Brown', 'John.Brown@Bro.com', NULL, 'Retail', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (893, 'Johnson Technology Solutions', 'Sarah Brown', 'Michael.Garcia@Joh.com', NULL, 'Education', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (894, 'Brown Technology Systems', 'David Garcia', 'Michael.Johnson@Bro.com', NULL, 'Education', '2026-04-06T15:26:44.964528', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1138, 'Smith Healthcare Inc', 'John Williams', 'John.Williams@Smi.com', NULL, 'Finance', '2026-01-11T11:38:28.276871', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1171, 'Davis Education Systems', 'Jane Miller', 'Lisa.Williams@Dav.com', NULL, 'Technology', '2026-01-11T11:38:38.012302', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1187, 'Williams Retail Inc', 'Robert Smith', 'John.Williams@Wil.com', NULL, 'Healthcare', '2026-01-11T11:38:38.012302', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1447, 'Miller Retail Co', 'David Jones', 'John.Smith@Mil.com', NULL, 'Retail', '2026-01-11T17:59:41.067557', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1453, 'Jones Retail Co', 'Robert Johnson', 'Jane.Brown@Jon.com', NULL, 'Manufacturing', '2026-01-11T17:59:41.067557', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1508, 'Smith Technology Inc', 'Robert Davis', 'Emily.Miller@Smi.com', NULL, 'Technology', '2026-01-12T17:55:09.485293', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1511, 'Brown Retail Inc', 'John Smith', 'Jane.Williams@Bro.com', NULL, 'Education', '2026-01-12T17:55:09.485293', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1531, 'Brown Technology Corp', 'Robert Smith', 'David.Williams@Bro.com', NULL, 'Healthcare', '2026-01-12T17:55:09.485293', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1538, 'Brown Healthcare Inc', 'Emily Miller', 'Lisa.Jones@Bro.com', NULL, 'Manufacturing', '2026-01-12T17:55:09.485293', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1603, 'Garcia Education Ltd', 'Emily Smith', 'Jane.Johnson@Gar.com', NULL, 'Technology', '2026-01-12T21:24:28.865077', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1654, 'Miller Finance Inc', 'David Johnson', 'Lisa.Johnson@Mil.com', NULL, 'Healthcare', '2026-01-12T21:24:28.865077', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1676, 'Garcia Technology Corp', 'Robert Garcia', 'Jane.Jones@Gar.com', NULL, 'Technology', '2026-04-19T07:36:09.355279', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1677, 'Johnson Education Systems', 'Emily Williams', 'Robert.Garcia@Joh.com', NULL, 'Finance', '2026-04-19T07:36:09.355279', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1695, 'Miller Technology Systems', 'Robert Davis', 'Lisa.Johnson@Mil.com', NULL, 'Manufacturing', '2026-04-19T07:36:09.355279', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1701, 'Davis Retail Solutions', 'Robert Garcia', 'David.Jones@Dav.com', NULL, 'Education', '2026-04-19T07:36:09.355279', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1718, 'Jones Healthcare LLC', 'Jane Jones', 'Michael.Garcia@Jon.com', NULL, 'Finance', '2026-04-19T07:36:09.355279', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1826, 'Davis Manufacturing Group', 'Robert Smith', 'Michael.Smith@Dav.com', NULL, 'Finance', '2026-04-19T07:36:20.953365', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1850, 'Brown Education Group', 'John Johnson', 'David.Smith@Bro.com', NULL, 'Education', '2026-04-19T07:36:20.953365', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1851, 'Garcia Manufacturing Group', 'Emily Jones', 'David.Jones@Gar.com', NULL, 'Healthcare', '2026-04-19T07:36:20.953365', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1900, 'Williams Retail Co', 'Lisa Jones', 'Michael.Miller@Wil.com', NULL, 'Technology', '2026-04-19T07:36:26.791667', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1951, 'Miller Retail Inc', 'Jane Smith', 'Emily.Davis@Mil.com', NULL, 'Technology', '2026-04-19T07:36:26.791667', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (1994, 'Miller Healthcare Group', 'John Davis', 'Jane.Johnson@Mil.com', NULL, 'Finance', '2026-04-19T07:37:32.957324', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2037, 'Smith Technology LLC', 'Robert Garcia', 'David.Miller@Smi.com', NULL, 'Technology', '2026-04-19T07:37:32.957324', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2049, 'Miller Retail Corp', 'Sarah Johnson', 'Sarah.Smith@Mil.com', NULL, 'Technology', '2026-04-19T07:37:32.957324', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2054, 'Miller Manufacturing Inc', 'John Williams', 'Michael.Miller@Mil.com', NULL, 'Healthcare', '2026-04-19T07:37:32.957324', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2062, 'Miller Manufacturing Inc', 'John Johnson', 'Jane.Davis@Mil.com', NULL, 'Manufacturing', '2026-04-19T07:37:32.957324', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2079, 'Jones Manufacturing Group', 'Robert Brown', 'Michael.Johnson@Jon.com', NULL, 'Manufacturing', '2026-04-19T07:37:45.194950', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2082, 'Garcia Education Systems', 'Lisa Williams', 'Robert.Garcia@Gar.com', NULL, 'Education', '2026-04-19T07:37:45.194950', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2090, 'Smith Technology Systems', 'David Jones', 'Michael.Williams@Smi.com', NULL, 'Finance', '2026-04-19T07:37:45.194950', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2103, 'Williams Retail Inc', 'Michael Miller', 'Sarah.Garcia@Wil.com', NULL, 'Retail', '2026-04-19T07:37:45.194950', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2108, 'Johnson Retail Solutions', 'Robert Davis', 'David.Miller@Joh.com', NULL, 'Healthcare', '2026-04-19T07:37:45.194950', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2142, 'Jones Technology Solutions', 'Sarah Garcia', 'Lisa.Miller@Jon.com', NULL, 'Education', '2026-04-19T07:37:45.194950', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2147, 'Jones Finance Group', 'Lisa Brown', 'Sarah.Johnson@Jon.com', NULL, 'Technology', '2026-04-19T07:37:45.194950', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2155, 'Miller Technology Co', 'John Davis', 'Lisa.Smith@Mil.com', NULL, 'Finance', '2026-04-19T07:37:45.194950', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2265, 'Jones Education Inc', 'Emily Jones', 'John.Brown@Jon.com', NULL, 'Healthcare', '2026-04-19T07:38:01.631458', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2289, 'Williams Technology Solutions', 'David Jones', 'John.Garcia@Wil.com', NULL, 'Education', '2026-04-19T07:38:18.667239', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2293, 'Brown Technology Corp', 'Jane Garcia', 'Emily.Garcia@Bro.com', NULL, 'Retail', '2026-04-19T07:38:18.667239', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2294, 'Williams Healthcare Systems', 'Robert Williams', 'Emily.Davis@Wil.com', NULL, 'Finance', '2026-04-19T07:38:18.667239', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2301, 'Davis Technology Ltd', 'Michael Jones', 'Lisa.Miller@Dav.com', NULL, 'Education', '2026-04-19T07:38:18.667239', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2319, 'Garcia Education Co', 'Lisa Johnson', 'Lisa.Williams@Gar.com', NULL, 'Education', '2026-04-19T07:38:18.667239', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2331, 'Brown Education Group', 'Lisa Miller', 'Emily.Miller@Bro.com', NULL, 'Healthcare', '2026-04-19T07:38:18.667239', NULL, NULL, NULL, NULL, NULL, 'USA');
INSERT INTO sales_demo_app.customers (customer_id, company_name, contact_name, email, phone, industry, created_at, metadata, domain, hq_city, hq_state, hq_state_abbr, hq_country) VALUES (2352, 'Williams Healthcare Inc', 'Michael Williams', 'Michael.Johnson@Wil.com', NULL, 'Education', '2026-04-19T07:38:18.667239', NULL, NULL, NULL, NULL, NULL, 'USA');


-- products: 15 rows
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (1, 'TitanDB Enterprise', 'Database', 'Demo seed product for enterprise database', '250000.00', '2026-02-21T18:11:22.129076', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (2, 'ClarityDB Guardian', 'Observability', 'Demo seed product for database observability', '120000.00', '2026-02-21T18:11:22.129076', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (3, 'OmniConnect Proxy', 'Platform', 'Demo seed product for connectivity and pooling', '180000.00', '2026-02-21T18:11:22.129076', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (4, 'Neuron Canvas', 'AI Platform', 'Demo seed product for AI workflow tooling', '90000.00', '2026-02-21T18:11:22.129076', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (5, 'Synapse AIOps', 'Automation', 'Demo seed product for automated ops', '140000.00', '2026-02-21T18:11:22.129076', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (6011, 'OmniConnect Proxy', NULL, 'OmniConnect Proxy is an intelligent, high-availability router and connection pooler that sits between your applications and your database fleet. It provides a unified endpoint for database access, optimizing traffic, enhancing security, and simplifying infrastructure management. By managing connections efficiently, OmniConnect ensures your database resources are never overwhelmed, delivering consistent performance and resilience even during peak loads or partial outages.', NULL, '2026-01-10T01:07:08.992825', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (6012, 'TitanDB Enterprise', NULL, 'TitanDB Enterprise is our flagship database server, built on a powerful open-source core and fortified with the advanced features required for mission-critical operations. It delivers unparalleled performance, rock-solid reliability, and comprehensive security controls for your most demanding applications. With 24/7/365 support, extensive partner integrations, and robust management tools, TitanDB Enterprise is the trusted foundation for your organization''s data infrastructure.', NULL, '2026-01-10T01:07:08.992825', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (6013, 'PillarDB Standard', NULL, 'PillarDB Standard bridges the gap between our open-source offering and our enterprise suite, providing a fully supported, commercially licensed database with key performance and security enhancements. It''s the ideal choice for businesses that need reliable, production-ready features, professional support, and certified security patches, all at an affordable price point. PillarDB Standard gives you the confidence to run your important applications without the complexity of our full enterprise-grade solution.', NULL, '2026-01-10T01:07:08.992825', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (6014, 'OS Guardian Support', NULL, 'OS Guardian Support offers a vital safety net for organizations leveraging our open-source database software in production. This subscription service provides you with expert technical assistance, on-demand help, and access to our extensive library of proprietary knowledge and training resources. It''s not a different software version—it''s the assurance that when you face a critical issue with your open-source deployment, our team of core engineers is on standby to help you resolve it quickly and efficiently.', NULL, '2026-01-10T01:07:08.992825', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (6015, 'CodeCraft DevKit', NULL, 'CodeCraft DevKit is a comprehensive suite of tools designed to streamline the database development lifecycle for your entire team. Integrated directly into your favorite IDE, this toolkit provides everything you need to design, build, test, and govern your database schemas with speed and precision. From visual schema design to automated testing and governance checks, CodeCraft empowers developers to write better, more efficient database code while maintaining organizational standards.', NULL, '2026-01-10T01:07:08.992825', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (6016, 'ClarityDB Guardian', NULL, 'ClarityDB Guardian is a unified observability and management platform that gives you complete, 360-degree control over your entire database estate. It moves beyond simple monitoring to provide deep diagnostic insights, intelligent alerting, and powerful performance tuning capabilities. From capacity planning to automated troubleshooting, Guardian is the DBA''s command center for ensuring the health, speed, and reliability of all your databases, regardless of where they are deployed.', NULL, '2026-01-10T01:07:08.992825', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (6017, 'Synapse AIOps', NULL, 'Synapse AIOps is an intelligent automation platform that infuses your IT operations with the power of artificial intelligence. It connects to your existing systems—from monitoring tools to service desks—to correlate data, identify root causes, and automate complex resolution workflows. By enabling natural language commands and agentic AI, Synapse transforms your operations from reactive firefighting to proactive, automated problem-solving.', NULL, '2026-01-10T01:07:08.992825', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (6018, 'Converge Lakehouse', NULL, 'Converge Lakehouse is a unified data platform that combines the low-cost, flexible storage of a data lake with the high-performance querying and transactional capabilities of a data warehouse. It allows you to store all of your data—structured, semi-structured, and unstructured—in a single, open-format repository. With Converge, you can run high-speed SQL analytics, BI reporting, and AI/ML workloads directly on your raw data, eliminating data silos and complex ETL pipelines.', NULL, '2026-01-10T01:07:08.992825', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (6019, 'Neuron Canvas', NULL, 'Neuron Canvas is a low-code/no-code visual platform for building, deploying, and managing generative AI applications. It empowers everyone—from business analysts to seasoned developers—to create powerful AI agents, chatbots, and data-driven workflows using an intuitive drag-and-drop interface. By connecting your enterprise data, APIs, and large language models (LLMs) in a secure and governable way, Neuron Canvas unlocks the value of AI for your entire organization.', NULL, '2026-01-10T01:07:08.992825', TRUE);
INSERT INTO sales_demo_app.products (product_id, product_name, category, description, base_price, created_at, is_core) VALUES (6020, 'Prometheus AI Factory', NULL, 'The Prometheus AI Factory is a comprehensive, end-to-end platform for building, deploying, and managing artificial intelligence at an enterprise scale. It provides a full-stack, secure solution that includes data ingestion pipelines, a visual agentic AI builder, high-performance model serving, and integrated AIOps for governance and monitoring. Prometheus is your sovereign AI infrastructure, giving you complete control over your models and data, enabling you to rapidly modernize applications and embed AI securely into the core of your business.', NULL, '2026-01-10T01:07:08.992825', TRUE);


-- sales_orders: 300 rows
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9, 1, 1, '2025-12-19T18:11:22.129076', 'won', '110000.00', NULL, '2026-02-01', NULL, '{"stage": "closed-won", "seed_key": "isg-deal-6", "demo_seed": true}'::jsonb, 'The company has a massive "shadow IT" problem. The CIO bought our platform as a way to *govern* and *enable* business-led development, rather than trying (and failing) to stop it.', 'high', 88, '2026-02-21T18:11:22.129076', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (26, 17, 1, '2026-01-01T00:00:00', 'lost', '34432.74', '2026-02-21', '2026-02-21', 'The "per-developer" license was too expensive, and the customer decided to stick with free tools like DBeaver.**', NULL, NULL, NULL, NULL, '2026-02-21T18:11:55.868607', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (217, 208, 1, '2025-11-28T00:00:00', 'won', '34794.00', '2026-02-21', '2026-02-21', NULL, NULL, 'A competitor''s tool required them to "pre-define" all the questions a user could ask. Our tool''s generative, ad-hoc nature allowed users to ask novel, complex questions, which won the technical bake-off.', NULL, NULL, '2026-02-21T18:12:01.990356', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (257, 248, 1, '2026-01-11T00:00:00', 'won', '52948.42', NULL, '2026-02-21', NULL, NULL, 'The legal team built an agent to analyze their contract database, which was previously just a "digital filing cabinet." Now they can ask, "Show me all contracts with non-standard liability clauses."', NULL, NULL, '2026-02-21T18:12:02.003803', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (313, 252, 2, '2026-01-30T00:00:00', 'lost', '67048.09', NULL, '2026-02-21', 'Lost to AWS, as their developers preferred to just call the "AWS Bedrock" API from their existing code rather than "onboard" to our "Factory."**', NULL, NULL, NULL, NULL, '2026-02-21T18:12:07.814005', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (330, 17, 2, '2026-02-12T00:00:00', 'lost', '12648.88', '2026-02-21', '2026-02-21', 'Our full-packet audit logging introduced 4% p99 latency in their PoC, which was too high for their high-frequency trading application.**', NULL, NULL, NULL, NULL, '2026-02-21T18:12:07.820374', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (336, 192, 2, '2026-01-11T00:00:00', 'won', '48248.29', '2026-02-21', '2026-02-21', NULL, NULL, 'They bought our "Synapse AIOps" and this "Builder" together. They use the "Builder" to "visually-create" the "automation-workflows" that "Synapse" runs.', NULL, NULL, '2026-02-21T18:12:07.822187', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (469, 120, 2, '2026-02-18T00:00:00', 'won', '75703.04', NULL, '2026-02-21', NULL, NULL, 'Their BI dashboards (Tableau) were "too static." This tool allowed them to "interactively drill down" by asking follow-up questions to the data, which was a "wow" moment for the exec team.', NULL, NULL, '2026-02-21T18:12:17.048113', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (534, 288, 2, '2026-02-21T02:27:50', 'won', '652.89', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Frequent "too many connections" errors were causing application-level failures and impacting end-user experience.', 'green', 88, '2026-02-21T02:27:50', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (550, 197, 2, '2026-02-21T05:45:03', 'won', '427.37', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They had 5 different data silos (Salesforce, Zendesk, Postgres, S3). The builder was able to connect to all 5, and they built a "Customer 360" agent that could answer questions by pulling data from all sources.', 'green', 93, '2026-02-21T05:45:03', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (584, 145, 1, '2026-02-21T10:46:14', 'lost', '171.12', '2026-02-21', '2026-02-21', 'The AI features were "too slow," with our API adding "2-3 seconds" of latency to their application, which was unacceptable.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 42, '2026-02-21T10:46:14', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (622, 117, 2, '2026-02-21T15:38:24', 'lost', '953.78', '2026-02-21', '2026-02-21', 'Product gap. Our sharding proxy does not support distributed transactions or cross-shard joins. This was a "day-one" requirement for their application, so our product was disqualified.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 82, '2026-02-21T15:38:24', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (625, 98, 2, '2026-02-21T09:22:57', 'lost', '185.83', '2026-04-25', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 70, '2026-02-21T09:22:57', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (645, 175, 1, '2026-02-21T01:43:11', 'won', '809.54', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The IT helpdesk was drowning in "how-to" tickets for VPN setup and password resets. They used our builder to create a chatbot that deflected 40% of these tickets in the first month.', 'red', 14, '2026-02-21T01:43:11', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (650, 259, 2, '2026-02-21T11:42:38', 'lost', '445.31', '2026-02-21', '2026-02-21', 'This was a "nice-to-have" add-on, and it was the first item cut when the customer''s training and enablement budget was reduced.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 94, '2026-02-21T11:42:38', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (661, 202, 1, '2026-02-21T21:45:31', 'won', '283.14', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The compliance team was terrified of "hallucinations." Our builder''s "citation-first" RAG, which *shows the source document* for every answer, was the key feature that got compliance to sign off.', 'green', 84, '2026-02-21T21:45:31', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (666, 162, 1, '2026-02-21T22:01:13', 'won', '661.64', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'An alert fired for "high latency." Their old script would just "restart." The Synapse AI Agent was able to "correlate" the alert with a "bad deployment" and trigger a "rollback" instead.', 'green', 76, '2026-02-21T22:01:13', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (699, 194, 1, '2026-02-21T18:10:30', 'won', '74.01', '2026-04-05', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 46, '2026-02-21T18:10:30', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (728, 28, 1, '2026-02-21T17:03:56', 'won', '486.83', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their "citizen developer" program failed because other tools were still too complex. Our visual, drag-and-drop interface was the first one their "power users" in finance could successfully adopt.', 'green', 89, '2026-02-21T17:03:56', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (737, 65, 2, '2026-02-21T09:39:13', 'won', '902.63', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They ran out of database connections. Guardian''s "connection pool usage" trend report would have shown them they were approaching their limit for weeks.', 'yellow', 58, '2026-02-21T09:39:13', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (759, 59, 2, '2026-02-21T12:45:46', 'won', '635.69', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their "fraud-detection" system was "batch-based" and would catch fraud "6 hours late." Converge''s "real-time" engine allowed them to "score" transactions *before* they were completed.', 'green', 87, '2026-02-21T12:45:46', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (778, 258, 2, '2026-02-21T06:51:22', 'lost', '931.88', '2026-02-21', '2026-02-21', 'The customer''s highly-skilled DevOps team opted to deploy and manage the open-source PgBouncer themselves to save on licensing costs.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 69, '2026-02-21T06:51:22', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (849, 226, 1, '2026-02-21T09:59:47', 'won', '414.42', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their "citizen developer" program failed because other tools were still too complex. Our visual, drag-and-drop interface was the first one their "power users" in finance could successfully adopt.', 'yellow', 69, '2026-02-21T09:59:47', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (868, 192, 2, '2026-02-21T14:03:19', 'lost', '912.27', '2026-02-21', '2026-02-21', 'The "all-or-nothing" subscription model was a poor fit. They wanted to buy 5 seats for their new hires, but our model required a site-wide license.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 71, '2026-02-21T14:03:19', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (896, 3, 1, '2026-02-21T08:41:37', 'lost', '20.97', '2026-02-21', '2026-02-21', 'Lost to AWS Lake Formation, as it was "good enough" for their basic table/column-level access control needs and was included with AWS.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 94, '2026-02-21T08:41:37', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (914, 123, 2, '2026-02-21T22:57:10', 'won', '21.86', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to continuously re-train their models on "fresh" data. Our Factory''s automated data pipeline was the only solution they saw that could connect their data lake to their models in real-time.', 'yellow', 59, '2026-02-21T22:57:10', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (924, 290, 2, '2026-02-21T16:47:17', 'won', '608.91', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The open-source patch for a CVE was complex and required a full version upgrade. PillarDB Standard provided a simple, back-ported patch for their current version.', 'yellow', 65, '2026-02-21T16:47:17', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (997, 24, 2, '2026-02-21T23:33:48', 'lost', '696.71', '2026-04-19', '2026-04-19', 'The customer is running on Red Hat Enterprise Linux and decided their existing RHEL contract, which offers "best-effort" support for our database, was sufficient.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 23, '2026-02-21T23:33:48', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1084, 288, 1, '2026-02-21T21:55:26', 'won', '164.68', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Migrating from a single-tenant to a multi-tenant sharded model. The proxy allowed them to migrate tenants one by one without any application downtime.', 'green', 97, '2026-02-21T21:55:26', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1168, 262, 2, '2026-02-21T12:24:33', 'won', '867.37', '2026-06-01', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 42, '2026-02-21T12:24:33', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1292, 121, 1, '2026-02-21T02:02:54', 'won', '946.12', '2026-06-03', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 40, '2026-02-21T02:02:54', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1335, 180, 1, '2026-02-21T08:37:23', 'won', '356.40', '2026-04-06', '2026-04-06', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They added an index, but the database didn''t use it. Guardian''s "index usage" report showed the index was redundant and "unused," saving them from a bad change.', 'red', 15, '2026-02-21T08:37:23', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1346, 40, 1, '2026-02-21T09:08:32', 'won', '288.50', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They wanted to "gamify" their operations. The ChatOps bot was configured to post "kudos" when someone fixed an issue, improving team morale.', 'yellow', 66, '2026-02-21T09:08:32', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1359, 117, 1, '2026-02-21T10:42:38', 'won', '14.74', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They had a "data sprawl" problem with no single source of truth. The DevKit''s central "data catalog" was purchased to be their new governance platform.', 'green', 100, '2026-02-21T10:42:38', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1391, 72, 2, '2026-02-21T03:42:02', 'won', '847.95', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their team was constantly "reinventing the wheel." They bought this to access our library of best-practice guides and performance tuning "cookbooks."', 'red', 21, '2026-02-21T03:42:02', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1403, 190, 1, '2026-02-21T20:24:12', 'won', '21.02', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They had no "data catalog." No one knew what data was available. Converge''s "AI-powered data catalog" automatically "crawled" their lake and "tagged" their data.', 'green', 81, '2026-02-21T20:24:12', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1466, 7, 2, '2026-02-21T01:41:15', 'won', '122.62', '2026-04-06', '2026-04-06', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their current "ChatOps" was just "notifications." Synapse provided "actionable" notifications (e.g., an alert with "Restart," "Investigate," or "Silence" buttons).', 'red', 20, '2026-02-21T01:41:15', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1481, 141, 2, '2026-02-21T05:24:27', 'won', '823.20', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The customer is a healthcare provider. HIPAA and data-residency rules required that all patient data *and* the AI models processing it must stay within their own data center.', 'green', 93, '2026-02-21T05:24:27', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1573, 228, 2, '2026-02-21T21:51:11', 'won', '222.65', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to automate a complex "disaster recovery" failover plan that involved 10 systems. Synapse''s "workflow-as-code" was the only tool that could orchestrate this.', 'red', 32, '2026-02-21T21:51:11', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1591, 86, 2, '2026-02-21T13:06:00', 'won', '468.23', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their CISO had shut down all generative AI projects due to a lack of control. Our Factory''s central governance dashboard and audit logs were the *only* way the CISO would approve re-starting.', 'green', 90, '2026-02-21T13:06:00', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1637, 214, 2, '2026-02-21T18:51:47', 'won', '99.34', '2026-04-06', '2026-04-06', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their BI dashboards (Tableau) were "too static." This tool allowed them to "interactively drill down" by asking follow-up questions to the data, which was a "wow" moment for the exec team.', 'red', 31, '2026-02-21T18:51:47', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1766, 138, 2, '2026-02-21T09:29:53', 'won', '71.51', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their old system could only "load-data" at "night." Their business "operates 24/7" and needed a "real-time" warehouse.', 'red', 37, '2026-02-21T09:29:53', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1769, 145, 1, '2026-02-21T07:28:10', 'lost', '814.87', '2026-04-10', '2026-04-10', 'The data-governance team "blocked" the purchase, as they would not allow a "low-code" tool to have direct-query access to their sensitive production data.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 46, '2026-02-21T07:28:10', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1850, 49, 1, '2026-02-21T00:08:57', 'lost', '667.14', '2026-04-06', '2026-04-06', 'Lost to GCP Vertex AI, as the data science team wanted to be on the same platform that provides access to the latest Gemini models.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 94, '2026-02-21T00:08:57', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1880, 99, 2, '2026-02-21T16:02:43', 'won', '456.62', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'An auditor "failed" them because they couldn''t explain *why* an AI model had denied a loan. Our Factory''s "model-lineage" and "explainability" features were the direct fix for this audit finding.', 'yellow', 42, '2026-02-21T16:02:43', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1915, 202, 1, '2026-02-21T02:40:05', 'won', '855.94', '2026-04-06', '2026-04-06', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'A business analyst in the finance department built a "quarterly report summarizer" app in a single afternoon during the PoC. This single demo proved the tool''s value to the CIO.', 'red', 27, '2026-02-21T02:40:05', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1952, 193, 2, '2026-02-21T08:16:54', 'won', '858.93', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They bought our "Synapse AIOps" and this "Builder" together. They use the "Builder" to "visually-create" the "automation-workflows" that "Synapse" runs.', 'yellow', 59, '2026-02-21T08:16:54', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1964, 138, 1, '2026-02-21T09:35:10', 'won', '590.10', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their e-commerce site was failing to handle Black Friday traffic levels. The advanced query optimizer in Enterprise cut their critical transaction times in half.', 'yellow', 60, '2026-02-21T09:35:10', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1982, 51, 1, '2026-02-21T19:14:45', 'lost', '980.08', '2026-04-06', '2026-04-06', 'The security automation project was put on hold after a major, unrelated security breach forced the team to focus all resources on remediation.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 23, '2026-02-21T19:14:45', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (1985, 109, 1, '2026-02-21T19:57:23', 'lost', '831.26', '2026-02-21', '2026-02-21', 'Instead of a self-serve subscription, the customer paid for a one-week, on-site "bootcamp" from a professional services firm.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 80, '2026-02-21T19:57:23', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2062, 34, 1, '2026-02-21T04:03:41', 'won', '330.40', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The open-source version couldn''t connect to their data visualization tool (e.g., Looker). The certified Looker connector was included in the Standard package.', 'yellow', 68, '2026-02-21T04:03:41', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2105, 238, 2, '2026-02-21T14:10:01', 'won', '688.51', '2026-05-28', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 76, '2026-02-21T14:10:01', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2200, 26, 1, '2026-02-21T14:47:25', 'won', '504.66', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'A read replica lagged too far behind the primary, and the application started serving stale data. The proxy''s replication-aware health checks detected the lag and automatically stopped routing traffic to that replica.', 'red', 33, '2026-02-21T14:47:25', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2222, 252, 1, '2026-02-21T03:22:17', 'lost', '95.36', '2026-05-04', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 37, '2026-02-21T03:22:17', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2258, 129, 2, '2026-02-21T05:30:57', 'won', '914.77', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Security team needed to consolidate audit logs from 50+ database nodes into their SIEM. The proxy provides a single, pre-formatted log stream, saving months of engineering effort.', 'green', 91, '2026-02-21T05:30:57', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2282, 227, 2, '2026-02-21T14:13:44', 'won', '574.57', '2026-04-06', '2026-04-06', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Customer needed to enforce a strict allow-list of known-good queries for a specific, high-risk application. OmniConnect was the only solution that could enforce query-level rules.', 'red', 30, '2026-02-21T14:13:44', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2310, 208, 1, '2026-02-21T10:38:13', 'won', '795.64', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They had no central "feature store." Their teams were rebuilding the same features (e.g., "customer 30-day spend") over and over. Our built-in feature store eliminated this duplicate work.', 'green', 92, '2026-02-21T10:38:13', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2353, 136, 1, '2026-02-21T02:15:19', 'won', '995.55', '2026-05-04', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 88, '2026-02-21T02:15:19', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2362, 128, 2, '2026-02-21T09:07:26', 'lost', '71.28', '2026-02-21', '2026-02-21', 'The governance rules were "too restrictive" and "slowed down" the data science team, who successfully lobbied to have the tool removed.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 87, '2026-02-21T09:07:26', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2394, 282, 1, '2026-02-21T07:27:02', 'lost', '810.09', '2026-02-21', '2026-02-21', 'Lost to cloud-native. The customer is migrating to Azure SQL Database, which has built-in, fully managed "Failover Groups" that cover their HA and DR needs. They did not want to pay for a third-party tool to replicate a feature their cloud provider gives them.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 29, '2026-02-21T07:27:02', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2476, 187, 1, '2026-02-21T19:22:17', 'lost', '644.27', '2026-04-02', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 91, '2026-02-21T19:22:17', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2479, 279, 2, '2026-02-21T02:34:06', 'won', '185.03', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their password reset process was manual and required a helpdesk ticket. Synapse was used to build a self-service "password reset" bot in Slack.', 'yellow', 50, '2026-02-21T02:34:06', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2483, 99, 2, '2026-02-21T23:33:13', 'won', '949.88', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The legal team built an agent to analyze their contract database, which was previously just a "digital filing cabinet." Now they can ask, "Show me all contracts with non-standard liability clauses."', 'yellow', 58, '2026-02-21T23:33:13', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2581, 41, 2, '2026-02-21T12:38:30', 'won', '428.87', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to load their QA database with 10 million rows of "realistic" (but fake) data. Guardian''s "test data generation" feature was the solution.', 'yellow', 65, '2026-02-21T12:38:30', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2628, 291, 1, '2026-02-21T02:57:50', 'won', '399.91', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Frequent "too many connections" errors were causing application-level failures and impacting end-user experience.', 'red', 11, '2026-02-21T02:57:50', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2662, 170, 2, '2026-02-21T15:07:13', 'won', '335.53', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their team didn''t have OS-level access. Guardian''s profiler captured all relevant OS stats (CPU, memory, disk queue) and correlated them with database activity in one UI.', 'red', 37, '2026-02-21T15:07:13', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2714, 112, 2, '2026-02-21T10:59:35', 'won', '319.09', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to enforce a policy that "no AI model can use race as a feature." Our governance module allowed them to enforce this policy-as-code and block any non-compliant model from being deployed.', 'green', 81, '2026-02-21T10:59:35', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2810, 24, 2, '2026-02-21T21:57:27', 'won', '964.16', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to perform a complex 50-step cloud migration. They used an AI agent to "supervise" the workflow, validate each step, and "ask for human help" if it hit an unknown error.', 'red', 25, '2026-02-21T21:57:27', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2841, 163, 2, '2026-02-21T19:03:56', 'won', '825.89', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their DevSecOps team estimated it would take 9 months to build and harden a secure, multi-tenant AI stack. Our pre-hardened Factory was deployed and secured in their VPC in one week.', 'red', 14, '2026-02-21T19:03:56', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2887, 141, 1, '2026-02-21T17:24:36', 'won', '571.59', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They had no central "feature store." Their teams were rebuilding the same features (e.g., "customer 30-day spend") over and over. Our built-in feature store eliminated this duplicate work.', 'red', 10, '2026-02-21T17:24:36', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2894, 100, 1, '2026-02-21T19:08:15', 'won', '977.40', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their data engineering team was manually writing and scheduling 100+ ETL scripts. The DevKit''s visual pipeline builder allowed them to manage this process in one place.', 'red', 31, '2026-02-21T19:08:15', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2937, 94, 2, '2026-02-21T18:34:40', 'lost', '911.21', '2026-02-21', '2026-02-21', 'The DevOps team has already mandated that all schema migrations are managed as "code" using the open-source tool Liquibase.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 99, '2026-02-21T18:34:40', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (2956, 234, 2, '2026-02-21T18:55:05', 'won', '462.62', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Customer needed to enforce a strict allow-list of known-good queries for a specific, high-risk application. OmniConnect was the only solution that could enforce query-level rules.', 'green', 96, '2026-02-21T18:55:05', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3037, 273, 1, '2026-02-21T16:47:38', 'won', '702.36', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their executive team complained they "have petabytes of data but can''t use it." Our builder was the "last mile" that finally connected their data lake to the actual business users via a simple chat interface.', 'green', 100, '2026-02-21T16:47:38', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3073, 54, 1, '2026-02-21T00:55:20', 'won', '473.36', '2026-04-06', '2026-04-06', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The QA team would report a bug as "the ''search'' page is slow," which wasn''t actionable. By giving QA access to Guardian, they could report the bug with a link to the *exact* slow query.', 'yellow', 54, '2026-02-21T00:55:20', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3075, 86, 2, '2026-02-21T21:47:13', 'lost', '45.89', '2026-04-06', '2026-04-06', 'The development and operations teams could not agree on a common tool, with ops wanting our tool and dev wanting to stay in GitLab CI.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 10, '2026-02-21T21:47:13', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3140, 7, 1, '2026-02-21T22:18:15', 'won', '562.72', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Customer is a startup. They needed production support but had zero buffer in their seed-stage budget for Enterprise. PillarDB Standard was the only option that fit their price point.', 'yellow', 52, '2026-02-21T22:18:15', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3185, 85, 2, '2026-02-21T03:03:49', 'won', '96.67', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The manager of the DBA team has a "continuous learning" budget, and this subscription was the most cost-effective way to provide training for the whole team.', 'green', 94, '2026-02-21T03:03:49', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3222, 187, 1, '2026-02-21T19:16:46', 'won', '1003.41', '2026-04-06', '2026-04-06', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their DevSecOps team estimated it would take 9 months to build and harden a secure, multi-tenant AI stack. Our pre-hardened Factory was deployed and secured in their VPC in one week.', 'yellow', 46, '2026-02-21T19:16:46', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3256, 150, 1, '2026-02-21T11:22:36', 'won', '769.51', '2026-04-06', '2026-04-06', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their proprietary data (e.g., new R\\&D chemical formulas) is their crown jewel. They bought our sovereign stack to ensure their "secret sauce" was not being used to train a public model.', 'green', 98, '2026-02-21T11:22:36', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3288, 126, 2, '2026-02-21T12:13:13', 'won', '981.73', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The legal team built an agent to analyze their contract database, which was previously just a "digital filing cabinet." Now they can ask, "Show me all contracts with non-standard liability clauses."', 'red', 33, '2026-02-21T12:13:13', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3324, 8, 2, '2026-02-21T06:50:03', 'won', '165.61', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'A developer writing a complex query would have to wait 10 minutes for it to run, only to find a syntax error. Our "real-time syntax checker" caught errors instantly.', 'yellow', 51, '2026-02-21T06:50:03', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3332, 283, 1, '2026-02-21T12:25:02', 'won', '440.43', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The VP of Sales wanted to build a "deal summary" agent but has zero technical skills. He was able to build a working prototype *himself* during the 1-hour demo, which immediately sold him.', 'green', 83, '2026-02-21T12:25:02', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3353, 128, 2, '2026-02-21T19:06:51', 'won', '106.09', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their "network-ops" team "built" a "chatbot" that can "answer" ("is ''server-x'' up?") and "do" ("ok, ''reboot'' ''server-x''").', 'red', 27, '2026-02-21T19:06:51', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3382, 117, 2, '2026-02-21T03:44:51', 'won', '828.50', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The manager of the DBA team has a "continuous learning" budget, and this subscription was the most cost-effective way to provide training for the whole team.', 'green', 75, '2026-02-21T03:44:51', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3392, 20, 1, '2026-02-21T14:34:20', 'won', '969.89', '2026-05-10', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 16, '2026-02-21T14:34:20', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3419, 261, 2, '2026-02-21T17:02:56', 'won', '93.71', '2026-04-06', '2026-04-06', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their "citizen developer" program failed because other tools were still too complex. Our visual, drag-and-drop interface was the first one their "power users" in finance could successfully adopt.', 'yellow', 56, '2026-02-21T17:02:56', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3432, 302, 1, '2026-02-21T16:09:35', 'won', '381.59', '2026-03-26', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 17, '2026-02-21T16:09:35', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3533, 73, 1, '2026-02-21T22:50:11', 'lost', '713.26', '2026-02-21', '2026-02-21', 'The customer is migrating to a fully-managed database (PaaS) to "eliminate" the need for support, rather than paying for a support contract.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 67, '2026-02-21T22:50:11', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3580, 248, 2, '2026-02-21T06:21:01', 'lost', '877.31', '2026-04-22', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 83, '2026-02-21T06:21:01', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3587, 300, 1, '2026-02-21T02:10:34', 'won', '19.43', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their two senior DBAs are nearing retirement. The support contract was purchased to de-risk the knowledge gap and backstop the more junior team.', 'green', 75, '2026-02-21T02:10:34', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3806, 97, 2, '2026-02-21T00:28:33', 'won', '555.33', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to continuously re-train their models on "fresh" data. Our Factory''s automated data pipeline was the only solution they saw that could connect their data lake to their models in real-time.', 'red', 25, '2026-02-21T00:28:33', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3824, 7, 2, '2026-02-21T18:46:41', 'won', '177.57', '2026-04-06', '2026-04-06', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their monitoring was siloed. Ops saw CPU, DBAs saw queries, and devs saw app errors. Guardian''s "full-stack" view allowed them to correlate an app error to a specific bad query.', 'green', 76, '2026-02-21T18:46:41', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3852, 73, 1, '2026-02-21T08:34:22', 'lost', '683.51', '2026-06-06', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 25, '2026-02-21T08:34:22', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (3951, 90, 2, '2026-02-21T13:36:37', 'won', '655.18', '2026-05-23', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 26, '2026-02-21T13:36:37', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4072, 295, 2, '2026-02-21T03:52:39', 'lost', '910.91', '2026-04-10', '2026-04-10', 'The customer''s in-house team built their own integration with their custom monitoring tool using our open-source client libraries.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 39, '2026-02-21T03:52:39', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4094, 153, 1, '2026-02-21T00:17:30', 'lost', '603.01', '2026-04-19', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 96, '2026-02-21T00:17:30', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4111, 19, 1, '2026-02-21T18:37:28', 'lost', '773.04', '2026-04-10', '2026-04-10', 'Product gap: Our platform lacked a "data versioning" (like DVC) or "model registry" feature, which was a hard requirement for their MLOps team.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 55, '2026-02-21T18:37:28', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4143, 155, 2, '2026-02-21T18:58:42', 'won', '327.48', '2026-03-26', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 93, '2026-02-21T18:58:42', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4169, 90, 1, '2026-02-21T06:16:00', 'lost', '899.03', '2026-05-05', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 60, '2026-02-21T06:16:00', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4177, 77, 1, '2026-02-21T02:26:19', 'won', '729.99', '2026-04-10', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 43, '2026-02-21T02:26:19', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4181, 190, 2, '2026-02-21T21:43:34', 'lost', '243.83', '2026-04-06', '2026-04-06', 'The project was canceled after the customer decided a sharding migration was too complex and risky, opting to vertically scale their monolith instead.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 23, '2026-02-21T21:43:34', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4242, 63, 2, '2026-02-21T18:24:43', 'won', '197.91', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They couldn''t "scale" their model-training. Converge''s "integration with Spark" allowed them to train models on "petabytes" of data in parallel.', 'red', 40, '2026-02-21T18:24:43', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4270, 327, 1, '2025-12-06T00:00:00', 'won', '52225.31', '2026-04-10', '2026-04-10', NULL, NULL, 'They are a small SaaS company, and application performance is their key differentiator. Standard gave them a competitive edge over rivals using basic open-source.', NULL, NULL, '2026-02-21T18:37:34.920126', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4303, 359, 1, '2026-02-07T00:00:00', 'won', '40095.57', NULL, '2026-04-10', NULL, NULL, 'They needed to automate their failover process. Guardian''s API allowed their script to query for "primary node health" before initiating the failover.', NULL, NULL, '2026-02-21T18:37:34.933967', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4338, 393, 2, '2026-01-22T00:00:00', 'won', '53461.33', '2026-04-06', '2026-04-06', NULL, NULL, 'The VP of Sales wanted to build a "deal summary" agent but has zero technical skills. He was able to build a working prototype *himself* during the 1-hour demo, which immediately sold him.', NULL, NULL, '2026-02-21T18:37:34.947555', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4483, 413, 1, '2025-12-23T00:00:00', 'lost', '53461.73', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-02-21T18:37:39.504660', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4556, 485, 2, '2025-12-16T00:00:00', 'won', '34054.40', NULL, '2026-04-06', NULL, NULL, 'They had 5 different data marts, creating "data silos." They consolidated all of them onto a single "Converge Lakehouse" to create a "single source of truth."', NULL, NULL, '2026-02-21T18:37:39.532417', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4558, 487, 2, '2026-01-01T00:00:00', 'lost', '35726.92', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-02-21T18:37:39.533003', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4684, 291, 2, '2026-02-21T16:14:38', 'won', '310.20', '2026-02-21', '2026-02-21', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The CEO was tired of waiting 3 days for the analytics team to build a report. He bought this so he could just *ask*, "What were our top 5 products in the NE region last quarter?" and get an instant answer.', 'red', 33, '2026-02-21T16:14:38', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4731, 531, 2, '2026-02-08T00:00:00', 'lost', '62194.43', '2026-04-10', '2026-04-10', 'The DBA team "vetoed" the purchase, as they do not want developers to "visually design" schemas. They prefer their existing, manual process of reviewing SQL scripts in a pull request.**', NULL, NULL, NULL, NULL, '2026-02-21T18:37:43.751709', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4735, 535, 1, '2026-01-01T00:00:00', 'won', '6531.93', '2026-04-06', '2026-04-06', NULL, NULL, 'The CEO had an "AI-mandate," but the team had no idea where to start. They bought our Factory as an "end-to-end platform" to kickstart their entire AI strategy, from data to production.', NULL, NULL, '2026-02-21T18:37:43.753122', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4750, 550, 2, '2025-11-26T00:00:00', 'won', '22541.42', '2026-04-10', '2026-04-10', NULL, NULL, 'Their BI dashboards (Tableau) were "too static." This tool allowed them to "interactively drill down" by asking follow-up questions to the data, which was a "wow" moment for the exec team.', NULL, NULL, '2026-02-21T18:37:43.759728', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4781, 581, 1, '2026-01-12T00:00:00', 'won', '91988.14', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-02-21T18:37:43.771597', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4813, 229, 2, '2026-02-21T14:25:18', 'won', '765.30', '2026-04-06', '2026-04-06', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They had 5 different teams building their own AI apps, creating "shadow AI" sprawl. Our Factory was bought to centralize and audit all AI development and deployment from a single-pane-of-glass.', 'red', 23, '2026-02-21T14:25:18', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4890, 120, 1, '2026-02-21T02:45:43', 'lost', '184.93', '2026-04-05', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 26, '2026-02-21T02:45:43', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (4924, 231, 2, '2026-02-21T08:10:00', 'lost', '662.18', '2026-05-14', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 81, '2026-02-21T08:10:00', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5215, 650, 1, '2026-02-24T00:00:00', 'won', '72597.66', '2026-04-06', '2026-04-06', NULL, NULL, 'Their "citizen developer" program failed because other tools were still too complex. Our visual, drag-and-drop interface was the first one their "power users" in finance could successfully adopt.', NULL, NULL, '2026-04-06T15:26:18.620083', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5302, 737, 2, '2025-11-03T00:00:00', 'lost', '32984.60', '2026-04-06', '2026-04-06', 'Our tool is for *developers*, but the customer''s DBAs do all troubleshooting, and they preferred their own tool (ClarityDB Guardian).**', NULL, NULL, NULL, NULL, '2026-04-06T15:26:42.303255', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5439, 874, 1, '2025-10-02T00:00:00', 'won', '52143.59', '2026-04-10', '2026-04-10', NULL, NULL, 'The compliance team was terrified of "hallucinations." Our builder''s "citation-first" RAG, which *shows the source document* for every answer, was the key feature that got compliance to sign off.', NULL, NULL, '2026-04-06T15:26:45.015939', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5442, 877, 1, '2025-08-07T00:00:00', 'won', '51250.55', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-04-06T15:26:45.017221', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5501, 66, 1, '2026-04-06T22:46:25', 'won', '312.14', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They wanted to build an agent that could "read" an inbound support email, "understand" the user''s intent, and "execute" the correct automation workflow.', 'red', 19, '2026-04-06T22:46:25', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5544, 498, 2, '2026-04-06T11:33:04', 'won', '913.18', '2026-06-04', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 82, '2026-04-06T11:33:04', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5616, 739, 1, '2026-04-06T07:55:58', 'won', '406.74', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They were using disk-level encryption, but their security team mandated database-level encryption to protect against privileged OS user attacks.', 'green', 92, '2026-04-06T07:55:58', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5712, 805, 2, '2026-04-06T22:14:48', 'won', '966.15', '2026-06-05', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 78, '2026-04-06T22:14:48', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5728, 606, 2, '2026-04-06T11:27:05', 'lost', '189.64', '2026-05-22', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 57, '2026-04-06T11:27:05', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5763, 741, 2, '2026-04-06T04:58:54', 'lost', '431.98', '2026-07-21', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 74, '2026-04-06T04:58:54', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5790, 20, 2, '2026-04-06T06:22:54', 'won', '233.48', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to be "GDPR compliant" and "process ''right-to-be-forgotten''" requests. The Lakehouse''s open-format (e.g., Apache Iceberg) allowed them to easily find and delete user records.', 'green', 81, '2026-04-06T06:22:54', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5798, 659, 2, '2026-04-06T09:14:52', 'won', '959.15', '2026-08-01', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 39, '2026-04-06T09:14:52', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5829, 813, 1, '2026-04-06T22:23:40', 'won', '365.00', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The "A-ha\\!" moment was when a marketing manager built an "ad copy generator" by simply pointing the builder at their existing product marketing documents, all without writing a single line of code.', 'red', 38, '2026-04-06T22:23:40', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5874, 288, 2, '2026-04-06T15:05:16', 'won', '938.44', '2026-04-06', '2026-04-06', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The compliance team was terrified of "hallucinations." Our builder''s "citation-first" RAG, which *shows the source document* for every answer, was the key feature that got compliance to sign off.', 'red', 24, '2026-04-06T15:05:16', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (5916, 679, 1, '2026-04-06T07:45:18', 'won', '574.24', '2026-06-17', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 80, '2026-04-06T07:45:18', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6011, 887, 1, '2026-04-06T21:38:58', 'won', '16.41', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They purchased our Lakehouse product last year, but only 20 analysts with SQL skills could use it. This builder was the "killer app" that allowed all 500 business users to get value from the lakehouse.', 'red', 30, '2026-04-06T21:38:58', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6085, 216, 2, '2026-04-06T07:33:36', 'won', '180.58', '2026-06-25', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 44, '2026-04-06T07:33:36', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6112, 773, 1, '2026-04-06T14:49:53', 'lost', '57.08', '2026-04-10', '2026-04-10', 'The "per-seat" license cost was too high to roll out to the 500+ "business users" they wanted to enable.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 67, '2026-04-06T14:49:53', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6166, 458, 1, '2026-04-06T22:57:30', 'won', '588.57', '2026-07-17', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 12, '2026-04-06T22:57:30', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6237, 28, 2, '2026-04-06T10:36:50', 'won', '15.20', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Customer needed to achieve their 99.99% uptime SLA, and their current DNS-based failover was too slow and unreliable.', 'red', 13, '2026-04-06T10:36:50', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6257, 311, 1, '2026-04-06T12:45:23', 'won', '306.24', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their "data gravity" was split between "on-prem" and "cloud." Converge''s "cross-cloud/hybrid" query engine was the only tool that could query both without moving data.', 'red', 22, '2026-04-06T12:45:23', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6265, 760, 2, '2026-04-06T21:00:21', 'lost', '159.86', '2026-04-10', '2026-04-10', 'The open-source integration was "good enough." They tested the "community" version of the backup connector they needed. While it wasn''t "certified" by us, it worked, so they decided to use it and save the license cost.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 38, '2026-04-06T21:00:21', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6266, 655, 1, '2026-04-06T21:59:29', 'lost', '798.37', '2026-04-19', '2026-04-19', 'Product gap: Our tool could not "trigger" a rollback, it could only "recommend" one, which didn''t meet their "hands-off" automation requirement.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 67, '2026-04-06T21:59:29', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6323, 558, 1, '2026-04-06T00:39:44', 'lost', '782.56', '2026-04-10', '2026-04-10', 'The customer hired an expert consultant who successfully tuned their open-source database to meet performance goals without upgrading.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 79, '2026-04-06T00:39:44', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6381, 829, 1, '2026-04-06T18:52:35', 'won', '889.85', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The sales operations team, who lives in spreadsheets, was able to connect a Google Sheet and build an "Account Briefing" agent, proving that non-technical users could build valuable tools.', 'yellow', 53, '2026-04-06T18:52:35', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6391, 635, 2, '2026-04-06T14:18:46', 'won', '172.03', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The finance team needed to query their general ledger, but only 2 senior accountants knew the complex table structure. They built an AI "data analyst" bot that everyone on the team can use.', 'green', 99, '2026-04-06T14:18:46', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6427, 122, 2, '2026-04-06T08:35:22', 'won', '186.98', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to integrate with their company''s single sign-on (SSO), but only needed basic LDAP, not the full SAML in Enterprise. Standard''s LDAP connector was the perfect fit.', 'yellow', 45, '2026-04-06T08:35:22', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6443, 816, 1, '2026-04-06T07:46:38', 'lost', '777.92', '2026-04-10', '2026-04-10', 'Price: Even our "budget" option was too expensive for the small business, which decided to go 100% open-source with "community-only" support.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 27, '2026-04-06T07:46:38', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6468, 893, 1, '2026-04-06T17:46:41', 'won', '847.78', '2026-06-26', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 95, '2026-04-06T17:46:41', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6499, 93, 1, '2026-04-06T18:11:39', 'won', '1004.90', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their Tier-2 app was starting to get more usage and hit performance walls. Upgrading to Standard was an "easy button" to get more headroom without re-architecting.', 'green', 91, '2026-04-06T18:11:39', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6531, 54, 2, '2026-04-06T15:52:04', 'won', '894.29', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Customer is migrating from a competing database (e.g., SQL Server) and needs to retrain their 20-person DBA team. The included certification path was the main driver.', 'red', 16, '2026-04-06T15:52:04', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6560, 290, 2, '2026-04-06T03:07:03', 'won', '987.45', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They were "stuck in PoC hell." They had 10 small AI projects that never got to production. Our Factory was the "production path" to operationalize and scale these models.', 'yellow', 71, '2026-04-06T03:07:03', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6565, 79, 1, '2026-04-06T05:49:45', 'lost', '170.68', '2026-05-06', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 12, '2026-04-06T05:49:45', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6583, 365, 1, '2026-04-06T12:31:56', 'won', '141.34', '2026-05-29', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 62, '2026-04-06T12:31:56', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6589, 148, 1, '2026-04-06T22:11:53', 'won', '848.30', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their BI tool (e.g., Tableau) was slow. Our Lakehouse''s high-concurrency query engine allowed them to have 100s of "concurrent" BI users without performance issues.', 'red', 27, '2026-04-06T22:11:53', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6600, 480, 1, '2026-04-06T09:21:19', 'lost', '578.91', '2026-04-10', '2026-04-10', 'Instead of a self-serve subscription, the customer paid for a one-week, on-site "bootcamp" from a professional services firm.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 45, '2026-04-06T09:21:19', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6622, 856, 2, '2026-04-06T06:38:15', 'won', '163.13', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They had a "mystery" problem that took a human 4 hours to solve. They "trained" an AI agent on the steps, and it can now solve the same problem in 2 minutes.', 'red', 21, '2026-04-06T06:38:15', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6626, 118, 2, '2026-04-06T22:02:29', 'won', '828.75', '2026-07-12', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 71, '2026-04-06T22:02:29', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6643, 690, 1, '2026-04-06T18:00:13', 'won', '66.57', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The finance team needed to query their general ledger, but only 2 senior accountants knew the complex table structure. They built an AI "data analyst" bot that everyone on the team can use.', 'green', 84, '2026-04-06T18:00:13', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6693, 634, 1, '2026-04-10T21:45:38', 'lost', '555.61', '2026-05-28', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 42, '2026-04-10T21:45:38', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6813, 648, 2, '2026-04-10T11:46:04', 'won', '173.11', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The team was frustrated with "Googling for answers." They wanted a single, curated, and correct source of truth for all their technical questions.', 'green', 89, '2026-04-10T11:46:04', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6871, 776, 1, '2026-04-10T08:01:58', 'lost', '808.39', '2026-05-14', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 86, '2026-04-10T08:01:58', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6889, 33, 2, '2026-04-10T01:46:38', 'won', '513.86', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their main competitor launched a new AI-powered feature. The board of directors approved the budget for our Factory the next day to "catch up and compete."', 'red', 30, '2026-04-10T01:46:38', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (6898, 225, 1, '2026-04-10T10:34:59', 'won', '1008.01', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Customer is launching in a new geographic region and needs to store user data locally for data sovereignty (e.g., GDPR). The proxy''s sharding rules allow them to route queries based on user\\_id to the correct regional database.', 'red', 30, '2026-04-10T10:34:59', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7087, 265, 2, '2026-04-10T06:37:38', 'won', '963.05', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to present a "high-level" business view of their data model to executives, but their current ERD was too complex. Our tool''s "views" let them create a simplified diagram.', 'red', 40, '2026-04-10T06:37:38', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7155, 350, 1, '2026-04-10T07:32:19', 'won', '391.09', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to feed database metrics into their enterprise monitoring tool, Datadog. The certified Datadog connector is only available with Enterprise.', 'red', 30, '2026-04-10T07:32:19', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7160, 488, 1, '2026-04-10T06:02:30', 'lost', '567.78', '2026-08-05', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 91, '2026-04-10T06:02:30', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7207, 833, 1, '2026-04-10T10:14:04', 'lost', '748.18', '2026-07-15', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 80, '2026-04-10T10:14:04', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7359, 697, 2, '2026-04-10T17:06:14', 'lost', '460.81', '2026-07-03', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 44, '2026-04-10T17:06:14', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7420, 872, 1, '2026-04-10T17:16:25', 'lost', '39.20', '2026-04-19', '2026-04-19', 'Lost on price. The customer''s WAF (Web Application Firewall) provider offered to "add on" their database firewall module for a 10% uplift, which was significantly cheaper than our standalone proxy license.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 13, '2026-04-10T17:16:25', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7425, 445, 1, '2026-04-10T19:49:24', 'won', '182.78', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their "time-to-respond" to a security alert was 4 hours. They bought Synapse to "automate the first 5 steps" of their (SOAR) playbook, like "enriching the alert" and "quarantining the user."', 'red', 18, '2026-04-10T19:49:24', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7459, 22, 1, '2026-04-10T00:00:53', 'lost', '211.21', '2026-04-10', '2026-04-10', 'Product gap: Our proxy''s inability to support cross-shard joins or distributed transactions was a "day-one" disqualifier for their application.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 34, '2026-04-10T00:00:53', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7521, 59, 2, '2026-04-10T17:55:05', 'won', '723.37', '2026-05-18', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 100, '2026-04-10T17:55:05', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7542, 105, 1, '2026-04-10T04:49:57', 'lost', '210.94', '2026-06-05', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 77, '2026-04-10T04:49:57', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7568, 529, 2, '2026-04-10T20:50:53', 'won', '584.01', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The legal team built an agent to analyze their contract database, which was previously just a "digital filing cabinet." Now they can ask, "Show me all contracts with non-standard liability clauses."', 'red', 18, '2026-04-10T20:50:53', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7632, 859, 1, '2026-04-10T18:25:57', 'lost', '786.26', '2026-04-10', '2026-04-10', 'The customer''s data engineering team has standardized on `dbt` for all transformation and data pipeline logic. They preferred `dbt`''s "code-first," SQL-based approach over our visual pipeline builder.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 18, '2026-04-10T18:25:57', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7645, 564, 2, '2026-04-10T21:41:13', 'lost', '582.68', '2026-07-16', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 42, '2026-04-10T21:41:13', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7657, 523, 2, '2026-04-10T08:43:06', 'won', '330.49', '2026-07-07', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 85, '2026-04-10T08:43:06', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7707, 142, 1, '2026-04-10T18:30:10', 'won', '341.78', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Writing complex SQL is slow and error-prone. The DevKit''s "visual query builder" allowed junior developers to be productive immediately.', 'red', 10, '2026-04-10T18:30:10', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7733, 835, 1, '2026-04-10T14:50:47', 'won', '1003.74', '2026-07-04', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 88, '2026-04-10T14:50:47', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7806, 894, 2, '2026-04-10T05:39:25', 'lost', '986.40', '2026-04-19', '2026-04-19', 'Poor value proposition. The customer felt the "Standard" support offering was just "a phone number to call" and didn''t include proactive tuning or guidance. They didn''t see the value and chose to self-support.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 27, '2026-04-10T05:39:25', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7835, 844, 2, '2026-04-10T00:10:36', 'lost', '712.49', '2026-06-07', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 57, '2026-04-10T00:10:36', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7894, 879, 2, '2026-04-10T13:31:20', 'lost', '914.91', '2026-07-14', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 85, '2026-04-10T13:31:20', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7963, 283, 2, '2026-04-10T18:02:09', 'won', '269.66', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They wanted to lower the "barrier to entry" for their operations team. Synapse''s natural language interface meant they could hire more junior talent.', 'green', 83, '2026-04-10T18:02:09', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (7984, 402, 2, '2026-04-10T04:26:45', 'won', '168.77', '2026-06-18', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 95, '2026-04-10T04:26:45', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8019, 870, 2, '2026-04-10T23:23:36', 'won', '990.10', '2026-07-13', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 99, '2026-04-10T23:23:36', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8025, 161, 1, '2026-04-10T17:56:08', 'won', '545.44', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their DevSecOps team estimated it would take 9 months to build and harden a secure, multi-tenant AI stack. Our pre-hardened Factory was deployed and secured in their VPC in one week.', 'yellow', 75, '2026-04-10T17:56:08', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8073, 287, 1, '2026-04-10T09:57:23', 'lost', '885.91', '2026-07-28', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 91, '2026-04-10T09:57:23', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8106, 365, 2, '2026-04-10T15:34:35', 'lost', '579.12', '2026-07-13', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 97, '2026-04-10T15:34:35', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8118, 157, 2, '2026-04-10T08:56:34', 'won', '423.34', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'User de-provisioning was a manual, 15-step process across 7 different systems. They built a "no-code" workflow that automates the entire process, eliminating the risk of a departing employee retaining access.', 'red', 16, '2026-04-10T08:56:34', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8130, 780, 2, '2026-04-10T14:49:25', 'lost', '576.21', '2026-04-19', '2026-04-19', 'The team is happy using free online tools (like draw.io or dbdiagram.io) for their ERDs and didn''t see the value in our "live-sync" paid feature.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 69, '2026-04-10T14:49:25', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8132, 529, 2, '2026-04-10T04:36:32', 'won', '346.74', '2026-05-26', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 81, '2026-04-10T04:36:32', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8136, 365, 2, '2026-04-10T03:01:03', 'won', '115.19', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their "network-ops" team "built" a "chatbot" that can "answer" ("is ''server-x'' up?") and "do" ("ok, ''reboot'' ''server-x''").', 'green', 92, '2026-04-10T03:01:03', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8298, 341, 2, '2026-04-10T06:34:20', 'lost', '49.87', '2026-05-27', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 88, '2026-04-10T06:34:20', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8322, 122, 2, '2026-04-10T16:25:27', 'lost', '887.17', '2026-04-19', '2026-04-19', 'Our "per-user" pricing was too expensive for them to roll out to their entire 5,000-person company for a simple "password-reset" bot.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 35, '2026-04-10T16:25:27', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8431, 824, 2, '2026-04-10T23:25:16', 'lost', '467.79', '2026-07-05', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 19, '2026-04-10T23:25:16', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8501, 162, 2, '2026-04-10T15:20:35', 'won', '458.10', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Security team needed to consolidate audit logs from 50+ database nodes into their SIEM. The proxy provides a single, pre-formatted log stream, saving months of engineering effort.', 'yellow', 42, '2026-04-10T15:20:35', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8502, 579, 1, '2026-04-10T14:03:27', 'won', '324.24', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their BI dashboards (Tableau) were "too static." This tool allowed them to "interactively drill down" by asking follow-up questions to the data, which was a "wow" moment for the exec team.', 'green', 81, '2026-04-10T14:03:27', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8605, 649, 1, '2026-04-10T13:17:43', 'won', '130.99', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to "version" their data, just like they "version" their code, to create "reproducible" ML models. Converge''s "data-versioning" capability (e.g., "time-travel") was the solution.', 'red', 24, '2026-04-10T13:17:43', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8628, 419, 2, '2026-04-10T01:33:18', 'lost', '726.59', '2026-06-13', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 87, '2026-04-10T01:33:18', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8643, 474, 2, '2026-04-10T00:41:53', 'won', '212.24', '2026-06-23', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 54, '2026-04-10T00:41:53', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8702, 577, 1, '2026-04-10T06:06:52', 'lost', '434.18', '2026-05-15', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 96, '2026-04-10T06:06:52', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8705, 636, 2, '2026-04-10T06:38:31', 'won', '725.33', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'A former employee was suspected of data theft, but the native database logs were insufficient for the investigation. This product provides the necessary "who, what, when, where" for all queries.', 'green', 99, '2026-04-10T06:38:31', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8739, 495, 2, '2026-04-10T14:52:01', 'lost', '87.87', '2026-07-05', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 71, '2026-04-10T14:52:01', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8802, 276, 1, '2026-04-10T16:41:01', 'lost', '116.40', '2026-06-16', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 75, '2026-04-10T16:41:01', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8905, 647, 2, '2026-04-10T06:00:05', 'won', '991.55', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their SRE team built an agent that automates their entire "server down" runbook. The agent now checks the service, restarts it, and scrapes the logs for the root cause before a human is even paged.', 'red', 33, '2026-04-10T06:00:05', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8938, 151, 1, '2026-04-10T10:57:06', 'won', '547.08', '2026-07-31', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 88, '2026-04-10T10:57:06', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (8995, 251, 1, '2026-04-10T23:15:59', 'won', '915.17', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to continuously re-train their models on "fresh" data. Our Factory''s automated data pipeline was the only solution they saw that could connect their data lake to their models in real-time.', 'yellow', 62, '2026-04-10T23:15:59', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9092, 831, 1, '2026-04-10T15:13:50', 'won', '397.14', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They wanted to modernize their on-premise legacy application but couldn''t move to the cloud due to data regulations. Our on-prem Factory allowed them to add "modern AI features" to their "legacy app."', 'yellow', 72, '2026-04-10T15:13:50', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9138, 75, 2, '2026-04-10T18:33:46', 'lost', '188.46', '2026-08-07', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 93, '2026-04-10T18:33:46', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9145, 521, 2, '2026-04-10T13:17:35', 'lost', '977.01', '2026-04-10', '2026-04-10', 'The "secure infrastructure" was "too rigid" and did not give their data scientists the "flexibility" and "admin rights" they needed to innovate.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 34, '2026-04-10T13:17:35', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9174, 891, 1, '2026-04-10T18:30:06', 'won', '419.44', '2026-07-21', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 82, '2026-04-10T18:30:06', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9190, 580, 2, '2026-04-10T20:43:36', 'lost', '745.29', '2026-05-10', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 76, '2026-04-10T20:43:36', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9200, 779, 1, '2026-04-10T07:59:14', 'won', '816.56', '2026-08-07', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 29, '2026-04-10T07:59:14', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9294, 274, 1, '2026-04-10T04:24:36', 'lost', '972.09', '2026-04-19', '2026-04-19', 'The customer''s highly-skilled DevOps team opted to deploy and manage the open-source PgBouncer themselves to save on licensing costs.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 80, '2026-04-10T04:24:36', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9307, 787, 2, '2026-04-10T03:14:07', 'won', '955.16', '2026-05-11', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 31, '2026-04-10T03:14:07', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9356, 28, 2, '2026-04-10T18:22:43', 'won', '118.68', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The PoC was won by a junior developer who used our Factory''s API to add a "GenAI chatbot" to their internal wiki in a single afternoon. The VP of Engineering was sold instantly.', 'green', 85, '2026-04-10T18:22:43', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9370, 691, 1, '2026-04-10T04:16:51', 'lost', '934.46', '2026-04-10', '2026-04-10', 'The customer was only interested in the troubleshooting features but had to buy the entire "DevKit," which was not a good value for them.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 98, '2026-04-10T04:16:51', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9417, 548, 1, '2026-04-10T02:08:33', 'won', '617.85', '2026-04-10', '2026-04-10', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The HR department built an "Employee Handbook Q\\&A" chatbot in two days. This bot became the C-level "showcase" for business-led innovation and drove the company-wide purchase.', 'red', 10, '2026-04-10T02:08:33', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9460, 23, 2, '2026-04-10T17:12:07', 'won', '978.49', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their DevSecOps team estimated it would take 9 months to build and harden a secure, multi-tenant AI stack. Our pre-hardened Factory was deployed and secured in their VPC in one week.', 'yellow', 69, '2026-04-10T17:12:07', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9613, 651, 2, '2026-04-10T12:47:17', 'won', '395.56', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'User de-provisioning was a manual, 15-step process across 7 different systems. They built a "no-code" workflow that automates the entire process, eliminating the risk of a departing employee retaining access.', 'green', 99, '2026-04-10T12:47:17', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9678, 787, 1, '2026-04-10T11:54:04', 'won', '243.16', '2026-06-10', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 51, '2026-04-10T11:54:04', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9695, 272, 2, '2026-04-10T22:11:44', 'lost', '496.42', '2026-08-03', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 85, '2026-04-10T22:11:44', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9703, 297, 1, '2026-04-10T09:47:11', 'won', '999.08', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to provide "data lineage" reports for their auditors. The governance module''s lineage tracking was the core feature they bought.', 'yellow', 71, '2026-04-10T09:47:11', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9826, 524, 1, '2026-04-10T05:26:24', 'won', '305.76', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'This was a CIO-level sale. The CIO did not want to buy 10 different, fragmented tools. Our "all-in-one-Factory" was the simple, consolidated, and strategic solution they needed.', 'yellow', 45, '2026-04-10T05:26:24', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (9869, 414, 2, '2026-04-10T00:10:48', 'lost', '582.57', '2026-04-19', '2026-04-19', 'The "query-in-place" performance was too slow in the PoC, and the customer decided it was faster to just ETL the data into their main data warehouse.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 72, '2026-04-10T00:10:48', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10025, 453, 1, '2026-04-10T12:35:58', 'won', '197.75', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their internal "Center of Excellence" bought the subscription to build their own best-practice guides based on our proprietary knowledge.', 'red', 35, '2026-04-10T12:35:58', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10115, 570, 2, '2026-04-10T16:21:19', 'won', '494.93', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to feed database metrics into their enterprise monitoring tool, Datadog. The certified Datadog connector is only available with Enterprise.', 'green', 82, '2026-04-10T16:21:19', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10227, 521, 1, '2026-04-10T02:07:38', 'won', '77.94', '2026-06-12', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 66, '2026-04-10T02:07:38', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10278, 280, 1, '2026-04-10T04:41:16', 'lost', '672.62', '2026-04-19', '2026-04-19', 'Failed PoC on performance. In their benchmark, our TDE feature introduced an 8% performance overhead on their write-heavy workload. The competitor''s TDE came in at \\<3% overhead, so we lost the bake-off.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 58, '2026-04-10T04:41:16', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10424, 1676, 37, '2026-01-29T00:00:00', 'won', '9820.05', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-04-19T07:36:09.364818', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10443, 1695, 19, '2026-02-09T00:00:00', 'won', '56647.93', '2026-04-19', '2026-04-19', NULL, NULL, 'A former employee was suspected of data theft, but the native database logs were insufficient for the investigation. This product provides the necessary "who, what, when, where" for all queries.', NULL, NULL, '2026-04-19T07:36:09.371505', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10449, 1701, 35, '2026-03-24T00:00:00', 'won', '45851.65', NULL, '2026-04-19', NULL, NULL, 'Management approved the move to open-source on the condition that "no production system runs unsupported." PillarDB Standard was the cheapest way to meet this mandate.', NULL, NULL, '2026-04-19T07:36:09.373519', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10466, 1718, 49, '2026-02-10T00:00:00', 'won', '13566.03', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-04-19T07:36:09.379750', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10599, 1951, 19, '2025-12-31T00:00:00', 'won', '99612.72', '2026-04-19', '2026-04-19', NULL, NULL, 'Internal security policy mandated real-time alerting on privileged data access (e.g., SELECT \\* on users table). Proxy''s logging enables this at the edge.', NULL, NULL, '2026-04-19T07:36:26.828740', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10727, 2079, 29, '2025-03-07T00:00:00', 'won', '59236.07', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-04-19T07:37:45.211547', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10730, 2082, 10, '2025-02-14T00:00:00', 'won', '5446.90', '2026-04-19', '2026-04-19', NULL, NULL, 'They needed to export their schema documentation for a compliance audit. The DevKit''s "Export to PDF/HTML" feature met the auditor''s request.', NULL, NULL, '2026-04-19T07:37:45.212826', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10738, 2090, 31, '2025-03-04T00:00:00', 'won', '92472.65', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-04-19T07:37:45.219181', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10795, 2147, 34, '2025-02-11T00:00:00', 'lost', '97770.26', '2026-04-19', '2026-04-19', 'Lost to AWS-native tools, as the customer preferred to use CloudTrail and RDS Performance Insights over adding a new third-party vendor.**', NULL, NULL, NULL, NULL, '2026-04-19T07:37:45.266890', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10803, 2155, 16, '2025-03-07T00:00:00', 'won', '3576.17', '2026-04-19', '2026-04-19', NULL, NULL, 'An auditor "failed" them because they couldn''t explain *why* an AI model had denied a loan. Our Factory''s "model-lineage" and "explainability" features were the direct fix for this audit finding.', NULL, NULL, '2026-04-19T07:37:45.273717', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10937, 2289, 7, '2025-10-03T00:00:00', 'lost', '3230.61', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-04-19T07:38:18.696955', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10942, 2294, 34, '2025-11-29T00:00:00', 'won', '45814.75', '2026-04-19', '2026-04-19', NULL, NULL, 'A developer writing a complex query would have to wait 10 minutes for it to run, only to find a syntax error. Our "real-time syntax checker" caught errors instantly.', NULL, NULL, '2026-04-19T07:38:18.706892', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10967, 2319, 32, '2025-10-21T00:00:00', 'lost', '85288.14', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-04-19T07:38:18.744312', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (10979, 2331, 44, '2025-10-16T00:00:00', 'lost', '73302.64', '2026-04-19', '2026-04-19', 'This was a "top-down" strategic purchase, but our "bottom-up" champion (the dev manager) failed to get "C-level" buy-in and budget.**', NULL, NULL, NULL, NULL, '2026-04-19T07:38:18.760305', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11139, 2049, 45, '2026-04-19T12:57:30', 'won', '183.53', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their "war room" calls for incidents were inefficient. With Synapse, the bot *is* the Scribe, auto-summarizing the incident timeline and actions taken from the chat.', 'green', 75, '2026-04-19T12:57:30', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11169, 2352, 5, '2026-04-19T04:55:54', 'won', '890.99', '2026-08-10', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 95, '2026-04-19T04:55:54', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11188, 277, 8, '2026-04-19T22:57:56', 'won', '942.12', '2026-08-07', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 41, '2026-04-19T22:57:56', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11190, 9, 43, '2026-04-19T15:38:26', 'lost', '181.53', '2026-04-19', '2026-04-19', 'Lost to open-source (PMM): The customer is already using Percona Monitoring and Management (PMM) for their MySQL fleet and decided to use it for our database as well.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 99, '2026-04-19T15:38:26', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11337, 510, 40, '2026-04-19T01:38:34', 'lost', '385.24', '2026-08-13', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 14, '2026-04-19T01:38:34', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11360, 1187, 20, '2026-04-19T07:00:43', 'won', '514.91', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'CIO signed off on a major open-source deployment on the one condition that they had a "break-glass" support contract with the original creators. This is that contract.', 'green', 94, '2026-04-19T07:00:43', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11437, 478, 9, '2026-04-19T12:40:53', 'won', '755.16', '2026-08-01', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 33, '2026-04-19T12:40:53', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11473, 1677, 17, '2026-04-19T07:19:09', 'won', '714.79', '2026-06-12', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 81, '2026-04-19T07:19:09', 1, 6020);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11497, 598, 9, '2026-04-19T08:18:03', 'lost', '842.67', '2026-07-22', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 47, '2026-04-19T08:18:03', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11541, 484, 25, '2026-04-19T09:36:12', 'lost', '812.29', '2026-07-27', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 91, '2026-04-19T09:36:12', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11581, 800, 33, '2026-04-19T19:23:36', 'won', '160.32', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed to automate a workflow that "read" a PO from a PDF attached to an email. Synapse''s "document AI" and "workflow" combination was the solution.', 'red', 12, '2026-04-19T19:23:36', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11601, 2293, 46, '2026-04-19T09:43:20', 'won', '17.12', '2026-05-31', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 28, '2026-04-19T09:43:20', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11617, 199, 47, '2026-04-19T12:12:42', 'won', '767.86', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their existing profiler was too high-level. Our "wait-event" analysis tool allowed them to see exactly *why* a query was slow (e.g., "waiting on disk I/O").', 'yellow', 71, '2026-04-19T12:12:42', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11650, 1138, 33, '2026-04-19T18:15:29', 'won', '516.56', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'A new code release caused a massive performance regression. Guardian''s "A/B performance comparison" view clearly showed the 10 queries that got slower after the release.', 'red', 28, '2026-04-19T18:15:29', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11693, 117, 9, '2026-04-19T16:02:36', 'won', '536.60', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They had 10 different "access-control" tools for 10 systems. Converge''s "central governance" allowed them to "define a policy once" and "apply it everywhere."', 'green', 86, '2026-04-19T16:02:36', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11843, 710, 35, '2026-04-19T19:55:11', 'lost', '134.02', '2026-04-19', '2026-04-19', 'Management "accepted the risk" of running open-source in production, viewing the support contract as an unneeded expense for a non-critical system.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 48, '2026-04-19T19:55:11', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11860, 1171, 45, '2026-04-19T13:52:55', 'won', '129.23', '2026-06-20', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 57, '2026-04-19T13:52:55', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11928, 1603, 5, '2026-04-19T22:27:36', 'won', '509.28', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Writing complex SQL is slow and error-prone. The DevKit''s "visual query builder" allowed junior developers to be productive immediately.', 'yellow', 73, '2026-04-19T22:27:36', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (11996, 555, 31, '2026-04-19T10:12:40', 'won', '371.07', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their serverless functions were overwhelming the database with short-lived connections. OmniConnect''s pooling was the only viable solution to make their architecture work.', 'yellow', 61, '2026-04-19T10:12:40', 1, 6011);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12014, 387, 50, '2026-04-19T05:17:08', 'won', '1005.90', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'An auditor "failed" them because they couldn''t explain *why* an AI model had denied a loan. Our Factory''s "model-lineage" and "explainability" features were the direct fix for this audit finding.', 'green', 90, '2026-04-19T05:17:08', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12050, 237, 22, '2026-04-19T09:45:37', 'lost', '33.81', '2026-04-19', '2026-04-19', 'The customer''s strategy is to "hire experts" rather than "train juniors," so they had no internal budget or need for training materials.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 88, '2026-04-19T09:45:37', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12079, 849, 43, '2026-04-19T16:34:45', 'lost', '884.01', '2026-07-03', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 79, '2026-04-19T16:34:45', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12095, 2054, 23, '2026-04-19T17:16:06', 'won', '294.97', '2026-07-11', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 41, '2026-04-19T17:16:06', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12104, 1654, 44, '2026-04-19T16:31:52', 'won', '433.71', '2026-06-10', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 12, '2026-04-19T16:31:52', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12147, 32, 50, '2026-04-19T12:50:02', 'won', '640.52', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their industry (e.g., local government) is now being targeted by hackers, and they can no longer risk running unpatched software.', 'green', 79, '2026-04-19T12:50:02', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12302, 2301, 24, '2026-04-19T12:24:55', 'won', '835.47', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'They needed granular RBAC to separate duties (e.g., "Data Scientists" can train, "Developers" can query, "Ops" can deploy). Our Factory was the only tool with this level of access control.', 'yellow', 65, '2026-04-19T12:24:55', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12346, 1447, 4, '2026-04-19T12:49:13', 'won', '371.95', '2026-06-22', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 81, '2026-04-19T12:49:13', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12464, 127, 15, '2026-04-19T21:18:23', 'won', '782.58', '2026-06-05', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 36, '2026-04-19T21:18:23', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12527, 1511, 48, '2026-04-19T10:26:09', 'won', '166.17', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'User de-provisioning was a manual, 15-step process across 7 different systems. They built a "no-code" workflow that automates the entire process, eliminating the risk of a departing employee retaining access.', 'red', 21, '2026-04-19T10:26:09', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12546, 10, 37, '2026-04-19T21:05:57', 'won', '72.85', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'Their proprietary data (e.g., new R\\&D chemical formulas) is their crown jewel. They bought our sovereign stack to ensure their "secret sauce" was not being used to train a public model.', 'red', 18, '2026-04-19T21:05:57', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12547, 811, 43, '2026-04-19T10:47:09', 'lost', '809.91', '2026-06-05', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 26, '2026-04-19T10:47:09', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12577, 525, 19, '2026-04-19T05:53:56', 'won', '591.90', '2026-06-20', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 44, '2026-04-19T05:53:56', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12741, 1538, 43, '2026-04-19T07:36:48', 'won', '166.05', '2026-07-16', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 79, '2026-04-19T07:36:48', 1, 3);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12806, 1695, 13, '2026-04-19T10:08:42', 'lost', '730.43', '2026-06-13', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 24, '2026-04-19T10:08:42', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12824, 118, 5, '2026-04-19T06:51:42', 'lost', '398.07', '2026-07-06', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 94, '2026-04-19T06:51:42', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12879, 1994, 11, '2026-04-19T04:55:15', 'won', '403.49', '2026-06-16', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 80, '2026-04-19T04:55:15', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12927, 1826, 20, '2026-04-19T06:19:30', 'won', '53.51', '2026-07-27', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 93, '2026-04-19T06:19:30', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12939, 2037, 46, '2026-04-19T11:44:46', 'lost', '552.32', '2026-07-19', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 35, '2026-04-19T11:44:46', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (12995, 2142, 33, '2026-04-19T00:52:27', 'lost', '254.91', '2026-05-26', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 37, '2026-04-19T00:52:27', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (13001, 1900, 18, '2026-04-19T09:43:52', 'won', '121.65', '2026-07-26', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 22, '2026-04-19T09:43:52', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (13040, 440, 5, '2026-04-19T00:33:45', 'won', '510.62', '2026-06-27', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 97, '2026-04-19T00:33:45', 1, 1);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (13330, 261, 42, '2026-04-19T07:00:37', 'lost', '1008.94', '2026-08-13', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 33, '2026-04-19T07:00:37', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (13380, 92, 25, '2026-04-19T04:06:46', 'won', '946.31', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'As a defense contractor, they have a strict "fully-airgapped" requirement. Our Factory was the only end-to-end AI platform that could be deployed and run with zero internet connectivity.', 'green', 81, '2026-04-19T04:06:46', 1, 6019);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (13410, 479, 8, '2026-04-19T23:04:18', 'lost', '914.73', '2026-04-19', '2026-04-19', 'Product gap: The deal was lost because we do not have a certified integration for their enterprise backup tool (Veritas NetBackup), and a competitor did.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 97, '2026-04-19T23:04:18', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (13455, 1531, 7, '2026-04-19T16:15:40', 'won', '476.16', '2026-07-17', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 18, '2026-04-19T16:15:40', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (13615, 2108, 16, '2026-04-19T23:36:04', 'won', '378.09', '2026-04-19', '2026-04-19', NULL, '{"source": "crm", "priority": "medium"}'::jsonb, 'The team calculated that one 4-hour outage on their Tier-2 app would cost more than a 3-year PillarDB Standard subscription. It was a simple ROI decision.', 'yellow', 57, '2026-04-19T23:36:04', 1, 6013);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (13707, 22, 8, '2026-04-19T21:44:55', 'lost', '702.46', '2026-07-01', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 89, '2026-04-19T21:44:55', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (13748, 584, 3, '2026-04-19T19:21:32', 'lost', '388.70', '2026-06-27', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 83, '2026-04-19T19:21:32', 1, 6016);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (13835, 2103, 2, '2026-04-19T08:24:42', 'won', '298.15', '2026-06-30', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 10, '2026-04-19T08:24:42', 1, 6018);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (14022, 342, 26, '2026-04-19T11:08:20', 'lost', '383.01', '2026-06-13', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 84, '2026-04-19T11:08:20', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (14042, 2062, 23, '2026-04-19T15:41:48', 'lost', '198.66', '2026-06-14', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 23, '2026-04-19T15:41:48', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (14060, 2103, 8, '2026-04-19T05:27:12', 'won', '879.32', '2026-07-28', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'green', 79, '2026-04-19T05:27:12', 1, 6015);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (14102, 1850, 27, '2026-04-19T11:11:43', 'won', '491.25', '2026-06-02', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 63, '2026-04-19T11:11:43', 1, 2);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (14298, 153, 40, '2026-04-19T13:12:35', 'won', '547.34', '2026-07-19', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 14, '2026-04-19T13:12:35', 1, 6012);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (14299, 2265, 48, '2026-04-19T10:19:47', 'won', '544.03', '2026-08-08', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 39, '2026-04-19T10:19:47', 1, 4);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (14575, 1851, 40, '2026-04-19T12:11:51', 'lost', '522.22', '2026-06-23', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 37, '2026-04-19T12:11:51', 1, 6014);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (14578, 1453, 17, '2026-04-19T19:51:04', 'lost', '86.66', '2026-04-19', '2026-04-19', 'The team struggled to "train" and "constrain" the agent during the PoC, and it kept making mistakes, leading to a loss of confidence.**', '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 17, '2026-04-19T19:51:04', 1, 6017);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (14952, 468, 35, '2026-04-19T06:11:54', 'lost', '502.25', '2026-08-14', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'yellow', 54, '2026-04-19T06:11:54', 1, 5);
INSERT INTO sales_demo_app.sales_orders (order_id, customer_id, salesperson_id, order_date, status, total_value, expected_close_date, actual_close_date, lost_reason, metadata, win_reason, forecast_confidence, confidence_pct, inserted_at, qty, product_id) VALUES (15007, 1508, 28, '2026-04-19T07:58:32', 'won', '662.50', '2026-06-05', NULL, NULL, '{"source": "crm", "priority": "medium"}'::jsonb, NULL, 'red', 39, '2026-04-19T07:58:32', 1, 2);


-- sales_notes: 974 rows
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12, 9, 1, 'Demo completed successfully. Customer loved the mobile app and offline sync capabilities. Sending contract this afternoon.', NULL, '2026-01-26T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16, 9, 1, 'Demo completed successfully. Customer loved the mobile app and offline sync capabilities. Sending contract this afternoon.', NULL, '2026-01-22T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (177, 26, 1, 'Introductory call with Sarah Miller to understand their needs. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Manufacturing requirements. Standard evaluation process. Williams Healthcare Solutions doing due diligence. Will send POC proposal for their review.', NULL, '2026-01-04T04:57:00.879557', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (178, 26, 1, 'Initial discovery meeting with Sarah Miller and their team. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Manufacturing requirements. Sarah Miller engaged throughout the discussion. Setting up intro call with our solutions architect.', NULL, '2026-01-12T01:43:11.176507', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (179, 26, 1, 'Continued evaluation discussions with Sarah Miller. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Manufacturing requirements. Meeting went as expected. Following standard sales process. Next: Send detailed proposal and pricing options.', NULL, '2026-01-20T02:24:25.065905', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (180, 26, 1, 'Rescheduled demo to accommodate their team.', NULL, '2026-01-27T06:53:02.274167', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (181, 26, 1, 'Demo went well with Williams Healthcare Solutions. Sarah Miller was engaged, especially around the data management challenges solution. They want to see a POC proposal.', NULL, '2026-01-31T20:23:52.903118', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (182, 26, 1, 'Final technical validation with Williams Healthcare Solutions. All concerns addressed including data management challenges. Sarah Miller pushing for approval this quarter.', NULL, '2026-02-05T00:27:10.648908', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (183, 26, 1, 'Proposal draft shared with Williams Healthcare Solutions.', NULL, '2026-02-09T08:23:48.426716', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (184, 26, 1, 'Comprehensive review session with Sarah Miller regarding Synapse AIOps implementation.

**Call Summary**
Productive discussion covering their core Manufacturing requirements. Sarah Miller led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

**Pain Points Discussed**
Sarah Miller outlined the issues they''re facing with their current approach:


Budget has been allocated for this initiative. They need a solution in place before end of fiscal year.

_Deal: $34432 | Stage: close | Champion: Sarah Miller_', NULL, '2026-02-21T23:11:55.947012', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (2701, 217, 1, 'Waiting on Williams Finance Corp decision.', NULL, '2025-12-05T21:48:22.006036', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (2702, 217, 1, 'Waiting on Williams Finance Corp decision.', NULL, '2025-12-13T01:25:31.060879', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (2703, 217, 1, 'Sent pricing sheet as requested.', NULL, '2025-12-16T16:31:24.052206', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (2704, 217, 1, 'Extended call with John Smith at Williams Finance Corp covering their Healthcare infrastructure.

**Call Summary**
Comprehensive call with John Smith and two other stakeholders from their technical team. Main focus was understanding how ClarityDB Guardian handles data management challenges. Good energy throughout the session.

**Timeline & Urgency**
Evaluation timeline shared by John Smith:
- Technical validation: Next 2 weeks
- Final vendor selection: End of month
- Contract negotiation: Following 2 weeks
- Target go-live: Within 60 days of signing

This is a real timeline - Williams Finance Corp''s VP has made this a priority.

_Deal: $34794 | Stage: middle | Champion: John Smith_', NULL, '2025-12-27T15:44:00.756677', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (2705, 217, 1, 'Demo and technical discussion with John Smith''s team. Deep dive into data management challenges and operational efficiency challenges. Their current workaround is manual and error-prone. Budget constraints mentioned. May need to adjust proposal. Next: Send detailed proposal and pricing options.', NULL, '2026-01-13T23:33:25.007496', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (2706, 217, 1, 'Contract review meeting with Williams Finance Corp legal and John Smith. Minor redlines on SLA terms. Should close by end of month.', NULL, '2026-01-15T13:12:49.141381', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (2707, 217, 1, 'Discussed account with manager.', NULL, '2026-01-28T03:56:33.732786', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (2708, 217, 1, 'Follow-up scheduled with John Smith.', NULL, '2026-02-11T02:43:30.695155', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (2709, 217, 1, 'Call with John Smith at Williams Finance Corp. Discussed data management challenges and next steps. Following up with additional materials.', NULL, '2026-02-19T03:34:58.237829', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3209, 257, 1, 'Initial discovery call with Michael Miller at Brown Technology LLC. They''re experiencing data management challenges. Scheduled follow-up demo for next week to show how Synapse AIOps addresses this.', NULL, '2026-01-11T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3210, 257, 1, 'Voicemail left - Michael Miller unavailable.', NULL, '2026-01-11T06:00:08.698113', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3211, 257, 1, 'Introductory call with Michael Miller to understand their needs. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Technology requirements. Michael Miller professional and thorough in their questions. Setting up intro call with our solutions architect.', NULL, '2026-01-11T20:26:29.002243', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3212, 257, 1, 'Good call with Michael Miller today.', NULL, '2026-01-15T10:35:05.852043', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3213, 257, 1, 'Shared Synapse AIOps documentation.', NULL, '2026-01-19T18:58:40.996398', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3214, 257, 1, 'Email bounced - need updated contact info.', NULL, '2026-01-20T13:39:41.195184', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3215, 257, 1, 'Updated CRM with latest info.', NULL, '2026-01-22T16:28:15.914944', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3216, 257, 1, 'Demo went well with Brown Technology LLC. Michael Miller was engaged, especially around the data management challenges solution. They want to see a POC proposal.', NULL, '2026-01-27T14:41:16.136877', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3217, 257, 1, 'Positive feedback from Brown Technology LLC team.', NULL, '2026-01-27T19:38:55.118864', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3218, 257, 1, 'Extended call with Michael Miller at Brown Technology LLC covering their Technology infrastructure.

**Call Summary**
Deep technical conversation with Brown Technology LLC''s evaluation team. Michael Miller has done their homework on our platform. Discussion centered on data management challenges and how we compare to their current solution.

**Competitive Landscape**
Competition includes **Elastic** (incumbent) and **Snowflake** (also evaluating). We''re differentiated on:
- Native support for their Technology workflows
- More flexible pricing model
- Faster time to value

They had a bad experience with Snowflake previously - opportunity to capitalize.

_Deal: $52948 | Stage: middle | Champion: Michael Miller_', NULL, '2026-01-28T00:08:27.001122', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3219, 257, 1, 'Productive session with Brown Technology LLC. Walked through architecture for handling data management challenges. Michael Miller impressed with our Technology experience.', NULL, '2026-02-01T10:04:41.130638', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3220, 257, 1, 'Detailed technical discussion with Brown Technology LLC team. Key stakeholder: Michael Miller.

**Call Summary**
Extended meeting covering both business and technical aspects. Michael Miller brought in their architect to validate our approach to data management challenges. Strong interest in our Technology experience.

**Target Use Cases**
Michael Miller outlined specific use cases they want to address with Synapse AIOps:


**Technical Requirements**
- CI/CD pipeline integration
- Container and Kubernetes support
- Audit logging and compliance reporting

_Deal: $52948 | Stage: middle | Champion: Michael Miller_', NULL, '2026-02-01T12:14:39.143837', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3221, 257, 1, '## Meeting Notes: Brown Technology LLC

Extended technical and business discussion with Michael Miller and their team at Brown Technology LLC. This was a pivotal meeting in the evaluation process.

### Call Summary
Deep technical conversation with Brown Technology LLC''s evaluation team. Michael Miller has done their homework on our platform. Discussion centered on data management challenges and how we compare to their current solution.

### Technical Requirements
- CI/CD pipeline integration
- Container and Kubernetes support
- API-first architecture for custom integrations

### Next Steps
1. Send final proposal with negotiated terms
2. Schedule contract review with Brown Technology LLC''s legal team
3. Prepare implementation timeline and resource plan
4. Michael Miller to get final budget approval from leadership
5. Target close date: End of month

### Target Use Cases
The Brown Technology LLC team is targeting the following deployment scenarios:


### Competitive Landscape
Competition includes **Databricks** (incumbent) and **Snowflake** (also evaluating). We''re differentiated on:
- Native support for their Technology workflows
- More flexible pricing model
- Faster time to value

They had a bad experience with Snowflake previously - opportunity to capitalize.

### Key Stakeholders
- **Michael Miller** (Primary Contact) - Engineering Manager, strong champion, driving the evaluation
- **Lisa** - Head of Platform, technical decision maker, needs to sign off on architecture
- **David** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the Director of IT. Michael Miller has direct access and influence.

---
**Deal Details:** $52948 ARR | **Stage:** late | **Industry:** Technology
**Champion:** Michael Miller | **Product:** Synapse AIOps', NULL, '2026-02-06T18:44:49.750076', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3222, 257, 1, 'Michael Miller OOO until Monday.', NULL, '2026-02-10T07:30:46.660261', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3223, 257, 1, 'Final technical review with Michael Miller and their team. Main discussion centered on data management challenges. Michael Miller mentioned this has been a pain point for over a year. High energy meeting - Michael Miller already talking implementation timeline. Next: Final contract review with legal teams.', NULL, '2026-02-11T12:29:20.549359', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3224, 257, 1, 'Michael Miller is reviewing internally.', NULL, '2026-02-12T20:44:05.252984', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3225, 257, 1, 'Waiting on Brown Technology LLC decision.', NULL, '2026-02-13T10:53:14.071194', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3226, 257, 1, 'Contract review meeting with Brown Technology LLC legal and Michael Miller. Minor redlines on SLA terms. Should close by end of month.', NULL, '2026-02-16T04:07:48.976910', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3227, 257, 1, 'Sync with Michael Miller. They''re working through data management challenges challenges. Synapse AIOps well-positioned to help.', NULL, '2026-02-21T21:40:53.815982', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3228, 257, 1, 'Sent email re: Synapse AIOps demo.', NULL, '2026-02-21T23:12:02.263186', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3229, 257, 1, 'Call with Michael Miller at Brown Technology LLC. Discussed data management challenges and next steps. Following up with additional materials.', NULL, '2026-02-21T23:12:02.263186', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3865, 313, 2, 'Detailed technical discussion with Johnson Healthcare Group team. Key stakeholder: Lisa Williams.

**Call Summary**
Productive discussion covering their core Manufacturing requirements. Lisa Williams led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

**Pain Points Discussed**
Key pain points identified during the discussion with Johnson Healthcare Group:


Budget has been allocated for this initiative. They need a solution in place before end of fiscal year.

_Deal: $67048 | Stage: early | Champion: Lisa Williams_', NULL, '2026-01-30T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3866, 313, 2, 'Extended call with Lisa Williams at Johnson Healthcare Group covering their Manufacturing infrastructure.

**Call Summary**
Deep technical conversation with Johnson Healthcare Group''s evaluation team. Lisa Williams has done their homework on our platform. Discussion centered on data management challenges and how we compare to their current solution.

**Competitive Landscape**
This is a competitive deal. **PTC** has existing relationship but Lisa Williams frustrated with their roadmap. **Siemens** in the mix but lacks Manufacturing expertise.

Our advantages: technical depth, Manufacturing focus, and Lisa Williams as a strong champion.

**Key Stakeholders**
- **Lisa Williams** (Primary Contact) - Platform Director, strong champion, driving the evaluation
- **David** - VP of Engineering, technical decision maker, needs to sign off on architecture
- **Amanda** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the Head of Platform. Lisa Williams has direct access and influence.

_Deal: $67048 | Stage: early | Champion: Lisa Williams_', NULL, '2026-01-30T05:47:03.907877', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3867, 313, 2, 'Had our first substantive call with Johnson Healthcare Group today. The team is struggling with data management challenges, which is impacting their operations significantly. Lisa Williams professional and thorough in their questions. Will send POC proposal for their review.', NULL, '2026-01-31T14:51:20.557174', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3868, 313, 2, 'Discovery session with Johnson Healthcare Group team. Primary pain point is data management challenges. Lisa Williams to loop in their technical lead for deeper dive.', NULL, '2026-02-01T17:44:13.270658', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3869, 313, 2, 'Had our first substantive call with Johnson Healthcare Group today. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Manufacturing requirements. Lisa Williams engaged throughout the discussion. Next: Schedule technical demo with their engineering team.', NULL, '2026-02-02T12:21:37.477446', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3870, 313, 2, 'Shared Neuron Canvas documentation.', NULL, '2026-02-03T00:16:27.415610', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3871, 313, 2, 'Continued evaluation discussions with Lisa Williams. Deep dive into data management challenges and operational efficiency challenges. Their current workaround is manual and error-prone. Meeting went as expected. Following standard sales process. Following up with technical architecture document.', NULL, '2026-02-05T00:40:42.105939', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3872, 313, 2, 'Productive session with Johnson Healthcare Group. Walked through architecture for handling data management challenges. Lisa Williams impressed with our Manufacturing experience.', NULL, '2026-02-06T06:55:31.727051', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3873, 313, 2, 'Deep-dive meeting with Johnson Healthcare Group stakeholders. Main discussion centered on data management challenges. Lisa Williams mentioned this has been a pain point for over a year. Good engagement from Lisa Williams. They see the potential. Scheduling reference call with similar Manufacturing customer.', NULL, '2026-02-07T07:11:22.857034', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3874, 313, 2, 'Sent email re: Neuron Canvas demo.', NULL, '2026-02-07T13:54:59.319342', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3875, 313, 2, 'Technical deep-dive with Johnson Healthcare Group''s engineering team. Good discussion on data management challenges and operational efficiency challenges. Lisa Williams asking for reference customers.', NULL, '2026-02-09T18:49:45.938593', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3876, 313, 2, 'Sent ROI calculator to Lisa Williams.', NULL, '2026-02-10T18:15:12.108318', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3877, 313, 2, 'Demo scheduled for Friday.', NULL, '2026-02-11T06:10:17.379619', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3878, 313, 2, 'Extended call with Lisa Williams at Johnson Healthcare Group covering their Manufacturing infrastructure.

**Call Summary**
Productive discussion covering their core Manufacturing requirements. Lisa Williams led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

**Timeline & Urgency**
Evaluation timeline shared by Lisa Williams:
- Technical validation: Next 2 weeks
- Final vendor selection: End of month
- Contract negotiation: Following 2 weeks
- Target go-live: Within 60 days of signing

This is a real timeline - Johnson Healthcare Group''s VP has made this a priority.

_Deal: $67048 | Stage: middle | Champion: Lisa Williams_', NULL, '2026-02-11T22:00:53.235676', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3879, 313, 2, 'Extended call with Lisa Williams at Johnson Healthcare Group covering their Manufacturing infrastructure.

**Call Summary**
Deep technical conversation with Johnson Healthcare Group''s evaluation team. Lisa Williams has done their homework on our platform. Discussion centered on data management challenges and how we compare to their current solution.

**Target Use Cases**
Lisa Williams outlined specific use cases they want to address with Neuron Canvas:


**Next Steps**
1. Prepare custom demo addressing key requirements
2. Schedule reference call with similar Manufacturing customer
3. Send preliminary pricing and packaging options

_Deal: $67048 | Stage: middle | Champion: Lisa Williams_', NULL, '2026-02-12T08:46:32.068788', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3880, 313, 2, 'Negotiation call with Lisa Williams and their procurement. Working through volume discount structure for $67048 deal.', NULL, '2026-02-12T22:01:53.817578', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3881, 313, 2, 'Shared Neuron Canvas documentation.', NULL, '2026-02-13T16:10:54.006568', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3882, 313, 2, 'Waiting for legal review.', NULL, '2026-02-15T02:33:55.929041', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3883, 313, 2, 'Pending response from stakeholders.', NULL, '2026-02-15T10:12:58.357970', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3884, 313, 2, 'Final technical validation with Johnson Healthcare Group. All concerns addressed including data management challenges. Lisa Williams pushing for approval this quarter.', NULL, '2026-02-16T15:28:42.426885', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3885, 313, 2, 'Pricing discussion with Lisa Williams. Deal size around $67048. They''re comparing us to two other vendors. Decision expected in 2 weeks.', NULL, '2026-02-16T19:06:10.090970', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3886, 313, 2, 'Extended call with Lisa Williams at Johnson Healthcare Group covering their Manufacturing infrastructure.

**Call Summary**
Extended meeting covering both business and technical aspects. Lisa Williams brought in their architect to validate our approach to data management challenges. Strong interest in our Manufacturing experience.

**Next Steps**
1. Send final proposal with negotiated terms
2. Schedule contract review with Johnson Healthcare Group''s legal team
3. Prepare implementation timeline and resource plan
4. Lisa Williams to get final budget approval from leadership

**Target Use Cases**
Key use cases driving this evaluation at Johnson Healthcare Group:


_Deal: $67048 | Stage: late | Champion: Lisa Williams_', NULL, '2026-02-18T18:46:49.888316', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3887, 313, 2, 'Discussion with Lisa Williams about next steps. Deep dive into data management challenges and operational efficiency challenges. Their current workaround is manual and error-prone. Excellent reception from the Johnson Healthcare Group team. They see clear value. Will follow up with additional materials.', NULL, '2026-02-21T04:18:55.171490', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3888, 313, 2, 'Comprehensive review session with Lisa Williams regarding Neuron Canvas implementation.

**Call Summary**
Deep technical conversation with Johnson Healthcare Group''s evaluation team. Lisa Williams has done their homework on our platform. Discussion centered on data management challenges and how we compare to their current solution.

**Next Steps**
1. Follow up with additional materials requested
2. Schedule next call with Lisa Williams
3. Send meeting summary and action items

**Technical Requirements**
- IoT device integration
- Real-time production monitoring
- Scalability to handle 10x current workload

_Deal: $67048 | Stage: close | Champion: Lisa Williams_', NULL, '2026-02-21T05:37:51.322941', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (3889, 313, 2, 'Comprehensive review session with Lisa Williams regarding Neuron Canvas implementation.

**Call Summary**
Deep technical conversation with Johnson Healthcare Group''s evaluation team. Lisa Williams has done their homework on our platform. Discussion centered on data management challenges and how we compare to their current solution.

**Timeline & Urgency**
Lisa Williams indicated a target decision date of end of quarter. Key timeline drivers:
- Current contract with existing vendor expires in 90 days
- New fiscal year budget available starting next month
- Manufacturing priority initiative tied to this solution

**Risk:** Delay could push to next budget cycle.

**Competitive Landscape**
Johnson Healthcare Group is also evaluating **Dassault** and **Siemens**. Our key differentiators:
- Superior handling of scaling challenges
- Stronger Manufacturing-specific features
- Better customer support reputation

Lisa Williams mentioned they''ve had issues with Dassault''s implementation complexity in the past.

_Deal: $67048 | Stage: close | Champion: Lisa Williams_', NULL, '2026-02-21T23:12:07.855574', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4085, 330, 2, 'Introductory call with Sarah Miller to understand their needs. Main discussion centered on data management challenges. Sarah Miller mentioned this has been a pain point for over a year. Sarah Miller professional and thorough in their questions. Next: Schedule technical demo with their engineering team.', NULL, '2026-02-12T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4086, 330, 2, 'Meeting confirmed for next week.', NULL, '2026-02-13T03:49:09.889694', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4087, 330, 2, 'Good intro meeting with Williams Healthcare Solutions. Sarah Miller outlined their Manufacturing challenges including data management challenges. Sending over technical overview.', NULL, '2026-02-13T06:36:12.156175', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4088, 330, 2, 'Scheduled intro call with stakeholder.', NULL, '2026-02-15T04:52:24.443085', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4089, 330, 2, 'Sarah Miller OOO until Monday.', NULL, '2026-02-15T10:48:34.396214', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4090, 330, 2, 'Meeting confirmed for next week.', NULL, '2026-02-16T20:56:28.532827', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4091, 330, 2, 'Proposal sent to Williams Healthcare Solutions.', NULL, '2026-02-18T11:31:17.725104', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4092, 330, 2, 'Final technical review with Sarah Miller and their team. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Manufacturing requirements. High energy meeting - Sarah Miller already talking implementation timeline. Next: Final contract review with legal teams.', NULL, '2026-02-18T12:57:26.904362', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4093, 330, 2, 'Demo scheduled for Friday.', NULL, '2026-02-19T17:25:45.072471', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4094, 330, 2, 'Meeting with Sarah Miller at Williams Healthcare Solutions today. Main discussion centered on data management challenges. Sarah Miller mentioned this has been a pain point for over a year. Sarah Miller is very enthusiastic about ClarityDB Guardian. Strong champion potential. Next meeting scheduled for next week.', NULL, '2026-02-21T12:50:51.899059', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4095, 330, 2, 'Call with Williams Healthcare Solutions team. The team is struggling with data management challenges, which is impacting their operations significantly. Excellent reception from the Williams Healthcare Solutions team. They see clear value. Next meeting scheduled for next week.', NULL, '2026-02-21T23:12:07.940694', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4173, 336, 2, 'Emily Miller is reviewing internally.', NULL, '2026-01-11T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4174, 336, 2, 'Moved meeting to next Thursday.', NULL, '2026-01-11T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4175, 336, 2, 'Initial discovery meeting with Emily Miller and their team. The team is struggling with data management challenges, which is impacting their operations significantly. Meeting went as expected. Following standard sales process. Next: Schedule technical demo with their engineering team.', NULL, '2026-01-13T11:50:30.946578', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4176, 336, 2, 'Kicked off the evaluation process with Williams Manufacturing Ltd. The team is struggling with data management challenges, which is impacting their operations significantly. Emily Miller engaged throughout the discussion. Next: Schedule technical demo with their engineering team.', NULL, '2026-01-23T10:13:03.152517', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4177, 336, 2, 'Initial discovery meeting with Emily Miller and their team. Deep dive into data management challenges and operational efficiency challenges. Their current workaround is manual and error-prone. Emily Miller engaged throughout the discussion. Following up with TitanDB Enterprise overview deck and case studies.', NULL, '2026-01-25T00:37:13.713617', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4178, 336, 2, 'Continued evaluation discussions with Emily Miller. Main discussion centered on data management challenges. Emily Miller mentioned this has been a pain point for over a year. Standard evaluation process. Williams Manufacturing Ltd doing due diligence. Next: Send detailed proposal and pricing options.', NULL, '2026-02-03T19:22:42.169116', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4179, 336, 2, 'Technical deep-dive with Williams Manufacturing Ltd''s engineering team. Good discussion on data management challenges and operational efficiency challenges. Emily Miller asking for reference customers.', NULL, '2026-02-15T08:03:55.615942', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4180, 336, 2, 'On hold pending internal review.', NULL, '2026-02-17T02:12:17.735113', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4181, 336, 2, 'Detailed technical discussion with Williams Manufacturing Ltd team. Key stakeholder: Emily Miller.

**Call Summary**
Deep technical conversation with Williams Manufacturing Ltd''s evaluation team. Emily Miller has done their homework on our platform. Discussion centered on data management challenges and how we compare to their current solution.

**Next Steps**
1. Prepare custom demo addressing key requirements
2. Schedule reference call with similar Healthcare customer
3. Send preliminary pricing and packaging options
4. Emily Miller to arrange meeting with their VP of Engineering

_Deal: $48248 | Stage: middle | Champion: Emily Miller_', NULL, '2026-02-18T21:46:28.648533', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4182, 336, 2, 'Pending response from stakeholders.', NULL, '2026-03-01T04:50:30.169199', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4183, 336, 2, 'Waiting on Williams Manufacturing Ltd decision.', NULL, '2026-03-03T06:36:30.194952', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4184, 336, 2, 'Contract review meeting with Williams Manufacturing Ltd legal and Emily Miller. Minor redlines on SLA terms. Should close by end of month.', NULL, '2026-03-04T21:30:07.185413', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4185, 336, 2, 'Comprehensive review session with Emily Miller regarding TitanDB Enterprise implementation.

**Call Summary**
Extended meeting covering both business and technical aspects. Emily Miller brought in their architect to validate our approach to data management challenges. Strong interest in our Healthcare experience.

**Technical Requirements**
- HIPAA compliance certification
- HL7/FHIR integration support
- Integration with existing authentication systems (SSO/SAML)

**Timeline & Urgency**
Evaluation timeline shared by Emily Miller:
- Technical validation: Next 2 weeks
- Final vendor selection: End of month
- Contract negotiation: Following 2 weeks
- Target go-live: Within 60 days of signing

This is a real timeline - Williams Manufacturing Ltd''s VP has made this a priority.

_Deal: $48248 | Stage: late | Champion: Emily Miller_', NULL, '2026-03-13T06:04:50.454412', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4186, 336, 2, 'Final technical review with Emily Miller and their team. Main discussion centered on data management challenges. Emily Miller mentioned this has been a pain point for over a year. Williams Manufacturing Ltd team receptive to our approach. Building momentum. Will send revised pricing based on today''s discussion.', NULL, '2026-03-14T02:58:58.167529', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4187, 336, 2, 'Moved meeting to next Thursday.', NULL, '2026-03-14T19:27:21.463992', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4188, 336, 2, 'Contract and pricing discussion with Williams Manufacturing Ltd. Main discussion centered on data management challenges. Emily Miller mentioned this has been a pain point for over a year. Positive vibes from the meeting. Emily Miller supportive. Preparing executive summary for their leadership.', NULL, '2026-03-29T19:48:19.411249', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4189, 336, 2, 'No update - following normal timeline.', NULL, '2026-04-05T12:19:35.806312', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4190, 336, 2, '## Technical Deep-Dive: Williams Manufacturing Ltd

Detailed walkthrough of TitanDB Enterprise capabilities with Williams Manufacturing Ltd''s engineering and business teams. Covered architecture, integration, and roadmap.

### Call Summary
Deep technical conversation with Williams Manufacturing Ltd''s evaluation team. Emily Miller has done their homework on our platform. Discussion centered on data management challenges and how we compare to their current solution.

### Target Use Cases
The Williams Manufacturing Ltd team is targeting the following deployment scenarios:


### Key Stakeholders
- **Emily Miller** (Primary Contact) - Technical Lead, strong champion, driving the evaluation
- **Lisa** - Director of IT, technical decision maker, needs to sign off on architecture
- **Sarah** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the Head of Platform. Emily Miller has direct access and influence.

### Timeline & Urgency
Evaluation timeline shared by Emily Miller:
- Technical validation: Next 2 weeks
- Final vendor selection: End of month
- Contract negotiation: Following 2 weeks
- Target go-live: Within 60 days of signing

This is a real timeline - Williams Manufacturing Ltd''s VP has made this a priority.

---
**Deal Details:** $48248 ARR | **Stage:** close | **Industry:** Healthcare
**Champion:** Emily Miller | **Product:** TitanDB Enterprise', NULL, '2026-04-10T14:19:48.091456', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (4191, 336, 2, 'Discussion with Emily Miller about next steps. The team is struggling with data management challenges, which is impacting their operations significantly. Encouraging discussion. Next steps agreed upon. Sending summary and action items.', NULL, '2026-04-11T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5941, 469, 2, 'Detailed technical discussion with Johnson Manufacturing Systems team. Key stakeholder: Sarah Davis.

**Call Summary**
Comprehensive call with Sarah Davis and two other stakeholders from their technical team. Main focus was understanding how Synapse AIOps handles data management challenges. Good energy throughout the session.

**Key Stakeholders**
- **Sarah Davis** (Primary Contact) - Platform Director, strong champion, driving the evaluation
- **Amanda** - Chief Architect, technical decision maker, needs to sign off on architecture
- **Lisa** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the Chief Architect. Sarah Davis has direct access and influence.

_Deal: $75703 | Stage: early | Champion: Sarah Davis_', NULL, '2026-02-18T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5942, 469, 2, 'Sarah Davis is reviewing internally.', NULL, '2026-02-19T04:24:12.615936', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5943, 469, 2, 'Comprehensive review session with Sarah Davis regarding Synapse AIOps implementation.

**Call Summary**
Productive discussion covering their core Healthcare requirements. Sarah Davis led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

**Next Steps**
1. Send Synapse AIOps technical overview and architecture documentation
2. Schedule demo with Sarah Davis''s engineering team (targeting next week)
3. Share Healthcare case studies and reference customers
4. Sarah Davis to gather internal requirements from their team

_Deal: $75703 | Stage: early | Champion: Sarah Davis_', NULL, '2026-03-11T12:15:44.536798', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5944, 469, 2, 'Deep-dive meeting with Johnson Manufacturing Systems stakeholders. Main discussion centered on data management challenges. Sarah Davis mentioned this has been a pain point for over a year. Standard evaluation process. Johnson Manufacturing Systems doing due diligence. Scheduling reference call with similar Healthcare customer.', NULL, '2026-03-12T08:44:53.659921', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5945, 469, 2, 'Demo and technical discussion with Sarah Davis''s team. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Healthcare requirements. Sarah Davis professional and thorough in their questions. Will prepare custom demo addressing data management challenges.', NULL, '2026-03-17T22:50:36.732380', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5946, 469, 2, 'Email follow-up sent to Sarah Davis.', NULL, '2026-03-29T17:46:44.053692', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5947, 469, 2, 'Demo and technical discussion with Sarah Davis''s team. Deep dive into data management challenges and operational efficiency challenges. Their current workaround is manual and error-prone. Johnson Manufacturing Systems team receptive to our approach. Building momentum. Will prepare custom demo addressing data management challenges.', NULL, '2026-04-11T06:58:26.565953', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5948, 469, 2, 'Confirmed meeting for next week.', NULL, '2026-04-12T13:18:55.260131', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5949, 469, 2, 'Comprehensive review session with Sarah Davis regarding Synapse AIOps implementation.

**Call Summary**
Productive discussion covering their core Healthcare requirements. Sarah Davis led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

**Competitive Landscape**
This is a competitive deal. **Cerner** has existing relationship but Sarah Davis frustrated with their roadmap. **Veeva** in the mix but lacks Healthcare expertise.

Our advantages: technical depth, Healthcare focus, and Sarah Davis as a strong champion.

_Deal: $75703 | Stage: late | Champion: Sarah Davis_', NULL, '2026-04-26T04:44:37.923664', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5950, 469, 2, 'Final technical review with Sarah Davis and their team. Deep dive into data management challenges and operational efficiency challenges. Their current workaround is manual and error-prone. Good engagement from Sarah Davis. They see the potential. Scheduling closing call for end of week.', NULL, '2026-05-01T18:15:46.001120', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5951, 469, 2, 'Final technical validation with Johnson Manufacturing Systems. All concerns addressed including data management challenges. Sarah Davis pushing for approval this quarter.', NULL, '2026-05-04T22:52:26.801490', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5952, 469, 2, 'No update - following normal timeline.', NULL, '2026-05-09T14:06:40.668529', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (5953, 469, 2, 'Meeting with Johnson Manufacturing Systems team went well. Sarah Davis is our champion, pushing internally. Deal progressing.', NULL, '2026-05-16T19:10:28.414662', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6475, 9, 1, 'Call Notes:
Current Challenges / Pain Points:
  - performance challenges affecting daily operations

Impact & Consequence: API response times degraded 40% in last quarter as user base grew. Lost two enterprise deals due to performance concerns in POC.

Current Solution / Competition: Using RDS PostgreSQL with default configuration. No query optimization or connection pooling. Application team unfamiliar with database tuning.

Key Questions Asked by Prospect:
  - What are common performance bottlenecks?
  - How do we identify slow queries?
  - Is there a managed solution for connection pooling?
  - What monitoring tools do you recommend?

Next Steps:
  - Set up performance audit session
  - Provide query analysis report
  - Demo connection pooling setup
  - Share performance optimization guide', 'call', '2026-01-28T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6476, 9, 1, 'I wanted to follow up on our previous discussion regarding Insightful Strategy Group''s need for enhanced compliance measures, as you expressed significant concern about adhering to relevant area. Our comprehensive compliance solution, tailored to address your unique needs, can provide substantial relief and ensure peace of mind moving forward.', NULL, '2026-01-13T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6535, 217, 2, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs. Scheduled follow-up call for next steps.', 'call', '2025-11-30T04:47:04', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6539, 534, 2, 'Customer discussed the following challenges:
1. Failing over to our DR site is a manual, multi-hour process.
2. We have to over-provision our database hardware just to handle the connection load, which is expensive.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-02-21T22:59:40', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6571, 550, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'meeting', '2026-02-21T23:14:17', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6621, 26, 2, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'internal', '2026-01-25T21:26:50', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6647, 584, 1, 'Prospect discussed the following challenges:
1. Our auditors are asking us to ''explain our AI,'' and we have no answer.
2. Our infrastructure does not support enforcing precise access rules on a per-query basis at this time.

Proposed Prometheus AI Factory as a solution to address these needs.', 'email', '2026-02-21T14:02:12', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6725, 622, 2, 'Customer discussed the following challenges:
1. Developers have to write complex, error-prone retry and failover logic into every microservice.

Proposed OmniConnect Proxy as a solution to address these needs.', 'email', '2026-02-21T21:53:30', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6730, 625, 2, 'Prospect discussed the following challenges:
1. We need to give our users a ''single data view,'' but our data is in 20 different places.
2. Our analytics are all ''batch-based.'' We have no ''real-time'' capabilities.

Proposed Converge Lakehouse as a solution to address these needs.', 'email', '2026-02-21T20:22:22', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6767, 645, 1, 'Customer discussed the following challenges:
1. We need to enforce ''role-based access control'' (RBAC) on who can ''use'' vs. ''train'' vs. ''deploy'' models.
2. We need to ''roll back'' our AI model to a previous version, but we can''t.

Proposed Prometheus AI Factory as a solution to address these needs. Action items documented and assigned.', 'email', '2026-02-21T11:28:09', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6771, 584, 1, 'Customer discussed the following challenges:
1. We need to ''fine-tune'' a model on our PII data, and we can''t do that in a public cloud.

Proposed Prometheus AI Factory as a solution to address these needs.', 'meeting', '2026-02-21T22:56:15', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6784, 650, 2, 'Customer discussed the following challenges:
1. We need consistent training across our entire global team.
2. We need to see real-world examples and reference architectures, not just command syntax.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-02-21T14:19:53', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6801, 661, 1, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'email', '2026-02-21T23:57:47', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6809, 645, 2, 'Customer discussed the following challenges:
1. We want to add a ''summarization'' feature to our app, but we don''t know how to call an LLM securely.
2. We need a repeatable, automated pipeline to ''process'' data for AI model training.

Proposed Prometheus AI Factory as a solution to address these needs.', 'email', '2026-02-21T07:41:14', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6817, 666, 1, 'Customer discussed the following challenges:
1. I need to find out ''who is the on-call for the database team?'' but I have to look in 3 different places.
2. We have monitoring ''silos.'' The network team can''t see the application logs, and the app team can''t see the network metrics.

Proposed Synapse AIOps as a solution to address these needs.', 'call', '2026-02-21T22:57:09', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6874, 699, 1, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'internal', '2026-02-21T20:19:28', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6924, 728, 1, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'email', '2026-02-21T22:49:26', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6943, 737, 2, 'Prospect went over the following challenges:
1. Our database can''t take advantage of modern, multi-core CPU architectures.
2. We are about to launch our most important new product, and we''re not confident the database can handle it.

Proposed TitanDB Enterprise as a solution to address these needs.', 'internal', '2026-02-21T09:58:41', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (6989, 759, 2, 'Customer discussed the following challenges:
1. We can''t ''time travel'' to see what our data looked like last Tuesday before it was corrupted.

Proposed Converge Lakehouse as a solution to address these needs.', 'meeting', '2026-02-21T23:11:43', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7032, 778, 2, 'Customer discussed the following challenges:
1. Our database has grown too large for a single server, but sharding is too complex to implement.
2. Our application regularly hits the ''too many connections'' error during peak traffic.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-02-21T16:00:52', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7075, 625, 1, 'Customer reviewed the following challenges:
1. We need our engineers to be more self-sufficient and less reliant on a few ''gurus'' on the team.
2. Our team needs to move faster, but they are slowed down by searching for answers.

Proposed OS Guardian Support as a solution to address these needs.', 'email', '2026-02-21T19:48:04', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7102, 217, 1, 'Prospect expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'email', '2026-02-06T01:36:05', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7171, 849, 1, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'call', '2026-02-21T18:33:54', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7173, 650, 2, 'Account went over the following challenges:
1. We spent 80 engineering hours last quarter troubleshooting the open-source database.

Proposed OS Guardian Support as a solution to address these needs.', 'email', '2026-02-21T22:39:47', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7175, 217, 1, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'call', '2025-12-08T03:22:05', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7196, 257, 1, 'Prospect expressed interest in Synapse AIOps for their data infrastructure needs.', 'meeting', '2026-01-12T11:36:16', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7216, 868, 2, 'Customer discussed the following challenges:
1. We need our team to get certified to prove their skills and build our internal expertise.

Proposed OS Guardian Support as a solution to address these needs.', 'email', '2026-02-21T19:10:39', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7266, 896, 1, 'Client discussed the following challenges:
1. Our users don''t want to learn 5 different query languages.
2. Our data is in a proprietary format, and our AI libraries can''t read it.

Proposed Converge Lakehouse as a solution to address these needs. Lisa Garcia requested additional information.', 'email', '2026-02-21T13:14:20', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7299, 914, 2, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs. Scheduled follow-up call for next steps.', 'meeting', '2026-02-21T23:54:47', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7302, 469, 1, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'internal', '2026-02-21T11:28:27', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7319, 924, 2, 'Prospect covered the following challenges:
1. We have 100+ important, but not ''mission-critical,'' apps that have no support.

Proposed PillarDB Standard as a solution to address these needs.', 'meeting', '2026-02-21T23:21:55', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7395, 666, 1, 'Customer discussed the following challenges:
1. We bought an automation tool, but it''s too complex, and no one is using it.
2. Our security tools and our IT operations tools don''t talk to each other.

Proposed Synapse AIOps as a solution to address these needs.', 'internal', '2026-02-22T03:01:13', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7437, 849, 1, 'Meeting notes for Jones Education Group: Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'meeting', '2026-02-21T23:53:32', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7462, 997, 2, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'meeting', '2026-02-21T23:45:52', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7523, 622, 2, 'Prospect covered the following challenges:
1. Our ''hot'' shards are constantly overloaded, while other shards are idle.

Proposed OmniConnect Proxy as a solution to address these needs. Sent proposal documentation via email.', 'email', '2026-02-21T22:14:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7555, 622, 1, 'Customer discussed the following challenges:
1. We failed a security audit because of a known SQLi vulnerability.

Proposed OmniConnect Proxy as a solution to address these needs.', 'email', '2026-02-21T21:48:35', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7629, 1084, 1, 'Meeting notes for Miller Healthcare Solutions: Customer discussed the following challenges:
1. Cross-shard queries are slow, complex, and require a separate aggregation service.
2. Our ''hot'' shards are constantly overloaded, while other shards are idle.

Proposed OmniConnect Proxy as a solution to address these needs.', 'email', '2026-02-21T21:56:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7712, 622, 2, 'Customer went over the following challenges:
1. Our application connection strings are hard-coded to a specific database IP, creating a single point of failure.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-02-21T22:16:11', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7741, 330, 2, 'Discussion with Williams Healthcare Solutions team: Prospect expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-02-21T21:23:34', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7764, 1168, 2, 'Customer talked about the following challenges:
1. Our data is our biggest asset, but we''re not treating it like one.
2. We have 10 different tools for monitoring: one for logs, one for metrics, one for traces. We can''t connect the dots.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-02-21T14:23:35', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7845, 313, 2, 'Call with Lisa Williams at Johnson Healthcare Group: Customer discussed the following challenges:
1. We need to trace a single user''s session from when they log in to when they log out.

Proposed ClarityDB Guardian as a solution to address these needs.', 'meeting', '2026-02-18T22:35:25', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (7846, 759, 1, 'Customer covered the following challenges:
1. We can''t apply ''table'' or ''column'' level security to files in a data lake.

Proposed Converge Lakehouse as a solution to address these needs.', 'meeting', '2026-02-21T19:54:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8019, 1292, 1, 'Customer discussed the following challenges:
1. Our customer support agents are wasting time ''swivel-chairing'' between 4 different apps to answer one customer question.

Proposed Neuron Canvas as a solution to address these needs.', 'call', '2026-02-21T08:09:51', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8107, 666, 2, 'Account discussed the following challenges:
1. We can''t automate our response to a threat; it''s all manual.
2. By the time we''ve triaged the alerts and escalated to the right team, the incident has been going for 30 minutes.

Proposed Synapse AIOps as a solution to address these needs.', 'internal', '2026-02-22T03:01:13', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8110, 1335, 1, 'Customer covered the following challenges:
1. We have no way to alert on query performance, only on host metrics (CPU, RAM).

Proposed ClarityDB Guardian as a solution to address these needs.', 'internal', '2026-02-21T23:04:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8124, 1346, 1, 'Customer discussed the following challenges:
1. Our AI projects fail because the ''business'' and ''IT'' are not aligned.
2. Our monitoring tools tell us what is broken, but not why it''s broken.

Proposed Synapse AIOps as a solution to address these needs.', 'internal', '2026-02-21T23:19:41', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8145, 1359, 1, 'Customer discussed the following challenges:
1. We want to know if this new index will actually improve performance, not just guess.
2. Our CI/CD pipeline tests our application code, but not our database performance.

Proposed CodeCraft DevKit as a solution to address these needs.', 'meeting', '2026-02-21T13:42:12', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8198, 1391, 2, 'Prospect discussed the following challenges:
1. Our monitoring only samples data every 5 minutes. The problem happened and was gone in 30 seconds.
2. Our developers are running resource-intensive test queries on the shared ''dev'' database, blocking other developers.

Proposed ClarityDB Guardian as a solution to address these needs.', 'meeting', '2026-02-21T15:47:29', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8225, 1403, 1, 'Customer discussed the following challenges:
1. We are seeing performance bottlenecks that we can''t tune away in the open-source software.

Proposed Converge Lakehouse as a solution to address these needs.', 'meeting', '2026-02-21T23:40:39', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8305, 645, 2, 'Client discussed the following challenges:
1. Our auditors are asking us to ''explain our AI,'' and we have no answer.

Proposed Prometheus AI Factory as a solution to address these needs.', 'internal', '2026-02-21T12:09:56', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8319, 661, 1, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs. Smith Technology Systems team seems very interested.', 'email', '2026-02-22T02:45:31', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8336, 1466, 2, 'Customer discussed the following challenges:
1. We can''t automate tasks that require ''checking'' a system first (e.g., ''if service is high-CPU, then restart it'').

Proposed Synapse AIOps as a solution to address these needs.', 'email', '2026-02-21T20:56:27', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8338, 217, 1, 'Follow-up with John Smith: Customer talked about the following challenges:
1. We only find out about a database problem when our customers call to complain.

Proposed ClarityDB Guardian as a solution to address these needs.', 'meeting', '2025-12-23T22:26:46', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8365, 1481, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'email', '2026-02-21T23:28:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8526, 1573, 2, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'email', '2026-02-21T22:37:31', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8551, 625, 1, 'Account went over the following challenges:
1. Our team is spending time trying to find workarounds for bugs instead of building features.
2. A account is threatening to leave because of a stability issue we can''t solve.

Proposed OS Guardian Support as a solution to address these needs. Sent proposal documentation via email.', 'email', '2026-02-21T23:08:31', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8567, 1591, 2, 'Call with Jane Johnson at Williams Technology Corp: Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'meeting', '2026-02-21T18:25:30', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8616, 330, 2, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'email', '2026-02-13T02:40:10', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8658, 1637, 2, 'Account discussed the following challenges:
1. We need to print out a data model for a whiteboarding session.

Proposed Neuron Canvas as a solution to address these needs.', 'email', '2026-02-21T22:17:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8720, 313, 1, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'internal', '2026-02-09T01:08:17', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8778, 1335, 1, 'Meeting notes for Jones Technology Solutions: Customer discussed the following challenges:
1. We want to do ''database-as-code,'' but we have no tools to support it.
2. Our ''capacity plan'' is a spreadsheet that someone updates manually once a quarter.

Proposed ClarityDB Guardian as a solution to address these needs.', 'email', '2026-02-21T23:41:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8898, 1766, 2, 'Customer discussed the following challenges:
1. Our warehouse and our lake are constantly out of sync, leading to conflicting reports.
2. We can''t ingest and query our IoT sensor data fast enough.

Proposed Converge Lakehouse as a solution to address these needs.', 'meeting', '2026-02-21T21:27:12', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (8903, 1769, 1, 'Customer discussed the following challenges:
1. Our business users don''t know SQL, so they can''t ''talk'' to our database.

Proposed Neuron Canvas as a solution to address these needs.', 'internal', '2026-02-21T10:00:49', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9052, 1573, 2, 'Customer talked about the following challenges:
1. We bought a ''workflow automation'' tool, but it''s too simple and can''t handle our complex logic.
2. Our ''security playbook'' is a 3-ring binder, not an automated workflow.

Proposed Synapse AIOps as a solution to address these needs.', 'internal', '2026-02-22T02:51:11', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9054, 1850, 1, 'Prospect expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'call', '2026-02-21T13:26:58', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9088, 778, 1, 'Customer went over the following challenges:
1. We acquired a company with a different sharding key, and we have no way to merge our platforms.
2. We can''t scale writes horizontally, creating a massive bottleneck for our fast-growing application.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-02-21T15:31:42', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9107, 1880, 2, 'Call with David Smith at Miller Education Solutions: Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-02-21T23:35:14', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9194, 1915, 1, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'email', '2026-02-21T21:15:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9257, 1952, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs. Lisa Smith requested additional information.', 'meeting', '2026-02-21T09:10:32', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9261, 1391, 1, 'Client went over the following challenges:
1. Our database is growing at 50 GB/day, and we don''t know which table or which application is causing it.

Proposed ClarityDB Guardian as a solution to address these needs.', 'email', '2026-02-21T20:34:20', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9276, 336, 1, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'call', '2026-01-26T16:55:09', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9280, 1964, 1, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'email', '2026-02-21T11:30:52', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9319, 1982, 1, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs. Sent proposal documentation via email.', 'internal', '2026-02-21T21:42:15', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9324, 1985, 1, 'Customer discussed the following challenges:
1. Our new hires are struggling because there''s no central, reliable source of information.

Proposed OS Guardian Support as a solution to address these needs. Garcia Finance LLC team seems very interested.', 'email', '2026-02-21T22:07:40', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9326, 1880, 2, 'Account expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-02-21T21:32:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9333, 584, 2, 'Customer discussed the following challenges:
1. We need a DBA to ''approve'' all queries, but this is a huge bottleneck for our developers.

Proposed ClarityDB Guardian as a solution to address these needs. Will follow up with Emily Miller next week.', 'call', '2026-02-21T19:11:26', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9335, 1391, 1, 'Account discussed the following challenges:
1. We can''t compare the performance of a query ''before'' and ''after'' our optimization.

Proposed ClarityDB Guardian as a solution to address these needs.', 'internal', '2026-02-21T11:21:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9389, 625, 1, 'Customer discussed the following challenges:
1. Our team''s skills are getting stale, and they aren''t up-to-date on the latest features.
2. Our staff turnover is high, and we are constantly retraining new people from scratch.

Proposed OS Guardian Support as a solution to address these needs.', 'email', '2026-02-21T21:00:51', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9439, 914, 1, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'call', '2026-02-22T03:57:10', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9452, 2062, 1, 'Customer discussed the following challenges:
1. We just need someone to call during business hours if our internal reporting database fails.

Proposed PillarDB Standard as a solution to address these needs.', 'meeting', '2026-02-21T19:56:29', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9523, 2105, 2, 'Customer discussed the following challenges:
1. Our ''self-service BI'' tool is a lie; it''s too complicated, and no one can use it.
2. We want to build an internal ''tool'' (e.g., ''summarize this legal document''), but we don''t have the budget for a full development team.

Proposed Neuron Canvas as a solution to address these needs.', 'internal', '2026-02-21T14:11:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9528, 1982, 2, 'Meeting notes for Garcia Healthcare Inc: Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'call', '2026-02-22T00:14:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9603, 1982, 1, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'internal', '2026-02-22T00:14:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9699, 2200, 1, 'Customer discussed the following challenges:
1. We can''t scale writes horizontally, creating a massive bottleneck for our fast-growing application.
2. Our serverless functions are overwhelming the database by opening thousands of short-lived connections.

Proposed OmniConnect Proxy as a solution to address these needs. Garcia Education Ltd team seems very interested.', 'email', '2026-02-21T23:28:08', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9733, 2222, 1, 'Customer went over the following challenges:
1. Our data is a mix of structured tables, JSON files, Parquet files, and CSVs. We can''t query it all.

Proposed Neuron Canvas as a solution to address these needs. Action items documented and assigned.', 'call', '2026-02-21T09:14:16', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9806, 2258, 2, 'Customer talked about the following challenges:
1. We have a legacy application that we can''t patch, and we know it''s vulnerable to SQLi.
2. Cross-shard queries are slow, complex, and require a separate aggregation service.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-02-21T09:13:34', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9812, 1292, 1, 'Customer talked about the following challenges:
1. Our IT ''knowledge base'' is a black hole; no one can find anything.
2. Our new-hire ''onboarding bot'' is giving incorrect information about our company benefits.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-02-21T13:03:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9849, 2282, 2, 'Customer discussed the following challenges:
1. We don''t know who is accessing what data in our database.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-02-21T22:56:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9851, 868, 1, 'Customer discussed the following challenges:
1. Our developers are writing inefficient queries because they don''t understand how the database works.

Proposed OS Guardian Support as a solution to address these needs.', 'meeting', '2026-02-21T21:05:42', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9896, 2310, 1, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-02-21T15:00:04', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9929, 1346, 1, 'Customer discussed the following challenges:
1. A human has to manually correlate 10 different alerts to find the one root cause.
2. Our SIEM generates 10,000 ''low'' and ''medium'' alerts a day, and we can''t investigate them all.

Proposed Synapse AIOps as a solution to address these needs.', 'meeting', '2026-02-21T20:02:32', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9978, 2353, 1, 'Customer talked about the following challenges:
1. Our enterprise backup solution (like Commvault or Veeam) doesn''t officially support our database.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-02-21T23:36:39', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (9993, 2362, 2, 'Discussion with Smith Education Group team: Account discussed the following challenges:
1. We need to use Active Directory or Okta groups to grant database permissions, but we can''t.
2. Our security team has flagged a CVE in our database, and we have no patch for it.

Proposed TitanDB Enterprise as a solution to address these needs.', 'call', '2026-02-21T20:08:46', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10057, 2394, 1, 'Spoke with Sarah Jones regarding their needs: Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'call', '2026-02-21T13:14:46', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10123, 2200, 1, 'Customer reviewed the following challenges:
1. It''s impossible to differentiate between application-level users and their database activity.

Proposed OmniConnect Proxy as a solution to address these needs.', 'email', '2026-02-21T22:44:57', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10128, 2105, 2, 'Customer discussed the following challenges:
1. Our ''knowledge base'' is updated every day, and we need our RAG app to see the ''fresh'' data immediately.
2. A user needs a password reset, but they have to file a ticket and wait an hour.

Proposed Neuron Canvas as a solution to address these needs.', 'email', '2026-02-21T20:24:22', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10150, 2310, 2, 'Client expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'call', '2026-02-21T16:46:54', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10175, 1591, 2, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs. Jane Johnson requested additional information.', 'call', '2026-02-21T19:39:50', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10223, 2476, 1, 'Discussion with Jones Manufacturing Group team: Customer covered the following challenges:
1. Our security team has flagged a CVE in our database, and we have no patch for it.
2. We''re spending weeks building custom scripts to move data from our database to our data warehouse.

Proposed TitanDB Enterprise as a solution to address these needs.', 'call', '2026-02-21T20:22:29', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10228, 2479, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'meeting', '2026-02-21T04:47:49', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10235, 2483, 2, 'Call with David Smith at Miller Education Solutions: Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'call', '2026-02-21T23:38:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10351, 257, 1, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'call', '2026-01-23T00:03:41', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10353, 534, 1, 'Customer covered the following challenges:
1. Cross-shard queries are slow, complex, and require a separate aggregation service.
2. Developers have to write complex, error-prone retry and failover logic into every microservice.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-02-21T16:37:21', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10386, 2581, 2, 'Prospect discussed the following challenges:
1. Our DBA spends 80% of their day firefighting instead of doing strategic work.
2. Our developers are not SQL experts, and they''re writing terrible, inefficient queries.

Proposed ClarityDB Guardian as a solution to address these needs.', 'internal', '2026-02-21T22:55:49', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10448, 2476, 1, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'email', '2026-02-22T00:22:17', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10449, 534, 1, 'Customer went over the following challenges:
1. Our database has grown too large for a single server, but sharding is too complex to implement.
2. The database is spending more CPU on connection setup/teardown than on running queries.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-02-21T11:09:30', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10481, 2628, 1, 'Customer discussed the following challenges:
1. Developers have to write complex, error-prone retry and failover logic into every microservice.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-02-21T19:18:16', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10517, 2479, 2, 'Client expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'internal', '2026-02-21T14:31:35', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10536, 2662, 2, 'Customer reviewed the following challenges:
1. We added an index, and it made other queries slower.

Proposed ClarityDB Guardian as a solution to address these needs.', 'call', '2026-02-21T22:56:47', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10540, 1880, 1, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs. Will follow up with David Smith next week.', 'email', '2026-02-21T21:09:49', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10600, 1346, 1, 'Customer covered the following challenges:
1. Currently, we lack a unified record-keeping system for monitoring activities within databases throughout the whole network of servers.
2. Our on-call engineer gets an alert on their phone, but they can''t do anything about it until they get to their laptop.

Proposed Synapse AIOps as a solution to address these needs.', 'email', '2026-02-21T15:59:39', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10615, 1766, 1, 'Customer discussed the following challenges:
1. Our data scientists want to use Python and Spark, but our data is locked in a SQL-only warehouse.
2. We can''t get ''real-time'' data into our warehouse; our BI reports are always a day old.

Proposed Converge Lakehouse as a solution to address these needs.', 'meeting', '2026-02-21T22:04:20', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10640, 759, 1, 'Client covered the following challenges:
1. We have ''data silos''—our BI team uses the warehouse, and our AI team uses the lake, and they''re looking at different data.

Proposed Converge Lakehouse as a solution to address these needs.', 'internal', '2026-02-21T19:32:12', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10642, 2714, 2, 'Prospect expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'call', '2026-02-21T14:11:28', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10734, 625, 1, 'Customer discussed the following challenges:
1. Our staff turnover is high, and we are constantly retraining new people from scratch.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-02-21T23:36:39', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10761, 1335, 2, 'Customer discussed the following challenges:
1. We are about to launch our most important new product, and we''re not confident the database can handle it.
2. Our ''security playbook'' is a 3-ring binder, not an automated workflow.

Proposed ClarityDB Guardian as a solution to address these needs.', 'internal', '2026-02-21T22:09:42', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10802, 330, 1, 'Customer discussed the following challenges:
1. Our data scientists are spending 80% of their time just finding and cleaning data.

Proposed ClarityDB Guardian as a solution to address these needs.', 'call', '2026-02-21T00:37:26', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10817, 2810, 2, 'Follow-up with David Williams: Customer discussed the following challenges:
1. When the site goes down, we get 500 alerts at once—from the app, the DB, the load balancer, the network. We don''t know where the real problem is.
2. We deployed new code, and our error rate spiked, but we didn''t catch it for an hour.

Proposed Synapse AIOps as a solution to address these needs.', 'meeting', '2026-02-21T22:51:34', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10858, 650, 2, 'Account reviewed the following challenges:
1. We''ve hit a critical performance bug, and our internal team is completely stuck.

Proposed OS Guardian Support as a solution to address these needs.', 'internal', '2026-02-21T23:43:30', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10871, 2841, 2, 'Customer discussed the following challenges:
1. Data governance measures cannot be enforced for each separate inquiry at this time.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-02-21T23:05:23', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10957, 2887, 1, 'Client discussed the following challenges:
1. We want our AI to cite its sources. ''I got this answer from the ''Employee Handbook, page 52''.

Proposed Neuron Canvas as a solution to address these needs.', 'internal', '2026-02-21T18:55:05', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (10970, 2894, 1, 'Customer covered the following challenges:
1. Our ''data governance'' policy is a 50-page Word document that nobody reads.
2. Our developer''s query runs fast on their machine, but slow in solutionion, and they don''t know why.

Proposed CodeCraft DevKit as a solution to address these needs.', 'internal', '2026-02-21T22:29:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11058, 2937, 2, 'Customer discussed the following challenges:
1. We need to compare the performance of database version A vs. version B before we upgrade.
2. Our log files are massive, and we can''t find the specific error message.

Proposed CodeCraft DevKit as a solution to address these needs.', 'meeting', '2026-02-21T22:39:20', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11096, 2956, 2, 'Call with Lisa Miller at Miller Manufacturing Co: Customer talked about the following challenges:
1. We need a vendor to help us with upgrade planning and best practices.
2. Adding a new shard to our cluster is a high-risk, manual process that can cause data inconsistencies.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-02-21T19:35:19', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11202, 625, 1, 'Customer went over the following challenges:
1. We have no access to advanced troubleshooting guides or architectural white papers.
2. We need our team to get certified to prove their skills and build our internal expertise.

Proposed OS Guardian Support as a solution to address these needs. Sent proposal documentation via email.', 'call', '2026-02-21T16:44:29', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11224, 1850, 2, 'Customer reviewed the following challenges:
1. Our data is ''locked away'' and inaccessible to 99% of our company.

Proposed Neuron Canvas as a solution to address these needs.', 'email', '2026-02-21T22:34:53', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11250, 3037, 1, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'email', '2026-02-21T23:26:47', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11309, 924, 1, 'Customer discussed the following challenges:
1. We need better caching and memory management than the community version offers.
2. We need better caching and memory management than the community version offers.

Proposed PillarDB Standard as a solution to address these needs.', 'meeting', '2026-02-21T22:06:11', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11314, 3073, 1, 'Customer discussed the following challenges:
1. We need to trace a single user''s session from when they log in to when they log out.

Proposed ClarityDB Guardian as a solution to address these needs.', 'internal', '2026-02-21T18:22:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11317, 3075, 2, 'Customer covered the following challenges:
1. We want to ''approve'' a dangerous action (like ''failover production'') from within chat, but we can''t.
2. Our team is burned out from repetitive, manual, ''toil'' tasks.

Proposed Synapse AIOps as a solution to address these needs.', 'meeting', '2026-02-21T23:51:46', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11371, 737, 2, 'Meeting notes for Johnson Finance LLC: Client discussed the following challenges:
1. Our developers are storing database credentials in code and config files, which is insecure.
2. We''re spending weeks building custom scripts to move data from our database to our data warehouse.

Proposed TitanDB Enterprise as a solution to address these needs.', 'internal', '2026-02-21T21:40:07', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11421, 3140, 1, 'Call with Jane Davis at Jones Healthcare Solutions: Prospect discussed the following challenges:
1. Our developers are complaining that their test environments are too slow, which slows down development.

Proposed PillarDB Standard as a solution to address these needs.', 'internal', '2026-02-21T23:26:05', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11450, 868, 2, 'Prospect discussed the following challenges:
1. Our team is skilled in other databases, but not this one, and we''re making ''rookie'' mistakes.
2. The cost of one major outage would be 10x the cost of this support subscription.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-02-21T23:17:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11494, 3185, 2, 'Meeting notes for Garcia Finance LLC: Customer discussed the following challenges:
1. Our team''s skills are getting stale, and they aren''t up-to-date on the latest features.
2. Our platformion database is down right now, and our only recourse is posting on a forum and hoping.

Proposed OS Guardian Support as a solution to address these needs.', 'internal', '2026-02-21T05:17:25', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11556, 3222, 1, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'internal', '2026-02-21T21:37:37', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11612, 2062, 2, 'Customer talked about the following challenges:
1. We need a vendor who is accountable for fixing bugs in the software.
2. The open-source drivers are unreliable and cause intermittent application errors.

Proposed PillarDB Standard as a solution to address these needs. Action items documented and assigned.', 'call', '2026-02-21T16:33:30', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11620, 3256, 1, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'meeting', '2026-02-21T13:45:47', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11638, 1766, 1, 'Customer covered the following challenges:
1. We have ''data silos''—our BI team uses the warehouse, and our AI team uses the lake, and they''re looking at different data.
2. I need to join our ''customer'' table in Oracle with our ''support tickets'' in Zendesk and our ''web logs'' in S3. It''s impossible.

Proposed Converge Lakehouse as a solution to address these needs.', 'email', '2026-02-21T15:10:42', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11669, 3288, 2, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'internal', '2026-02-21T12:14:43', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11738, 3324, 2, 'Customer discussed the following challenges:
1. Our data is not ''analytics-ready'' fast enough, so our business insights are delayed.

Proposed CodeCraft DevKit as a solution to address these needs.', 'email', '2026-02-21T10:27:49', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11755, 3332, 1, 'Customer covered the following challenges:
1. We need to budget for 2026, and we have no idea how much our database costs will grow.

Proposed ClarityDB Guardian as a solution to address these needs.', 'email', '2026-02-21T21:19:59', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11787, 3353, 2, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-02-21T23:31:15', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11834, 469, 1, 'Client expressed interest in Synapse AIOps for their data infrastructure needs. Sarah Davis requested additional information.', 'call', '2026-02-19T18:17:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11846, 3382, 2, 'Prospect went over the following challenges:
1. Our investors are asking about our business continuity plan, and ''community support'' isn''t a good answer.
2. We don''t know the ''gotchas'' of upgrading to a new version.

Proposed OS Guardian Support as a solution to address these needs.', 'email', '2026-02-21T08:48:07', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11859, 3392, 1, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'email', '2026-02-21T22:01:07', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11907, 3419, 2, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-02-21T21:44:52', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11931, 3432, 1, 'Customer discussed the following challenges:
1. We can''t justify the high cost of an enterprise license for our dev/test environments.
2. Our analytics dashboards for our Tier 2 apps are taking too long to load.

Proposed PillarDB Standard as a solution to address these needs.', 'meeting', '2026-02-21T16:29:06', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (11996, 3075, 2, 'Account discussed the following challenges:
1. We want to ''democratize'' our operations, but the tools are too complex.
2. We can''t ''quarantine'' an infected machine automatically; we have to wait for an analyst to do it.

Proposed Synapse AIOps as a solution to address these needs.', 'email', '2026-02-22T02:47:13', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12020, 997, 1, 'Spoke with David Williams regarding their needs: Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'internal', '2026-02-22T04:33:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12041, 737, 2, 'Follow-up with Jane Davis: Customer discussed the following challenges:
1. We can''t separate ''duty of care'' from ''duty to administer''; our admins see everything.
2. We have no control over the encryption keys; our cloud provider manages them all.

Proposed TitanDB Enterprise as a solution to address these needs.', 'meeting', '2026-02-21T18:35:57', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12123, 3533, 1, 'Call with Lisa Brown at Davis Retail Inc: Customer discussed the following challenges:
1. We''ve been running with a known bug for 6 months because the workaround is too painful to remove.
2. Our database doesn''t support partitioning, so our large tables are becoming unmanageable.

Proposed TitanDB Enterprise as a solution to address these needs.', 'meeting', '2026-02-21T23:20:41', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12214, 3580, 2, 'Call notes for Brown Technology LLC: Customer discussed the following challenges:
1. We have no version control for our data pipelines; if one breaks, it''s a nightmare to fix.
2. Our developers are spending 30% of their time just writing boilerplate SQL and CREATE scripts.

Proposed CodeCraft DevKit as a solution to address these needs.', 'call', '2026-02-21T19:51:11', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12229, 3587, 1, 'Call with Lisa Smith at Williams Retail Solutions: Customer talked about the following challenges:
1. We need our engineers to be more self-sufficient and less reliant on a few ''gurus'' on the team.
2. We love open-source, but our CTO is worried about running our business on unsupported software.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-02-21T19:36:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12263, 26, 2, 'Client expressed interest in Synapse AIOps for their data infrastructure needs.', 'meeting', '2026-02-15T12:52:36', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12315, 868, 2, 'Customer discussed the following challenges:
1. Our team is wasting time on blogs and forums, finding conflicting and outdated advice.
2. The cost of one major outage would be 10x the cost of this support subscription.

Proposed OS Guardian Support as a solution to address these needs.', 'email', '2026-02-21T22:34:08', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12320, 868, 2, 'Account covered the following challenges:
1. We keep ''rediscovering'' solutions to problems our team has already solved.
2. We just hired three new DBAs, and we have no formal way to train them on this database.

Proposed OS Guardian Support as a solution to address these needs.', 'internal', '2026-02-21T23:48:14', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12481, 2662, 2, 'Follow-up with Michael Smith: Prospect went over the following challenges:
1. Setting up monitoring for a new database is a 100-step manual process, so we just don''t do it.

Proposed ClarityDB Guardian as a solution to address these needs.', 'call', '2026-02-21T20:22:44', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12530, 3580, 1, 'Customer discussed the following challenges:
1. Onboarding a new developer takes forever because they can''t understand our complex data model.
2. Developers are using varchar(8000) for everything, which is inefficient and a security risk.

Proposed CodeCraft DevKit as a solution to address these needs.', 'meeting', '2026-02-21T16:34:32', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12593, 584, 1, 'Follow-up with Emily Miller: Customer discussed the following challenges:
1. Our ''legacy'' business processes are not ''AI-ready''.
2. We have 100 ''AI experiments'' but 0 ''AI products'' in production.

Proposed Prometheus AI Factory as a solution to address these needs.', 'internal', '2026-02-21T19:04:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12640, 3185, 2, 'Customer discussed the following challenges:
1. Our offeringion database is down right now, and our only recourse is posting on a forum and hoping.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-02-21T23:21:46', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12654, 3806, 2, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'email', '2026-02-21T00:46:50', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12685, 3824, 2, 'Account reviewed the following challenges:
1. Our database is growing at 50 GB/day, and we don''t know which table or which application is causing it.
2. We''re launching a new marketing campaign, and we have no idea if the database can handle the 5x traffic increase.

Proposed ClarityDB Guardian as a solution to address these needs. Action items documented and assigned.', 'meeting', '2026-02-21T22:58:26', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12723, 778, 2, 'Customer discussed the following challenges:
1. Database maintenance (patching, upgrades) requires a full application outage.
2. We acquired a company with a different sharding key, and we have no way to merge our platforms.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-02-21T13:55:25', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12732, 3852, 1, 'Call with Lisa Brown at Davis Retail Inc: Customer discussed the following challenges:
1. A simple vulnerability in our web form allowed an attacker to drop a critical table.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-02-21T11:59:58', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12786, 666, 1, 'Customer discussed the following challenges:
1. When we hire a new employee, it takes IT, HR, and Finance 3 days to get all their accounts set up.

Proposed Synapse AIOps as a solution to address these needs.', 'internal', '2026-02-22T03:01:13', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12827, 1769, 1, 'Customer talked about the following challenges:
1. We want to build a ''chatbot'' for our customers, but we don''t want it to ''make up'' answers.
2. Data governance measures cannot be enforced for each separate inquiry at this time.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-02-21T19:54:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12904, 26, 2, 'Prospect expressed interest in Synapse AIOps for their data infrastructure needs.', 'meeting', '2026-02-19T17:10:36', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12921, 3951, 2, 'Customer went over the following challenges:
1. Our model was found to be ''biased'' against a certain demographic, and it''s a huge legal and PR risk.

Proposed Prometheus AI Factory as a solution to address these needs.', 'meeting', '2026-02-21T15:37:33', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (12962, 2476, 1, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'meeting', '2026-02-22T00:22:17', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13023, 3332, 1, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'call', '2026-02-21T19:02:39', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13070, 924, 1, 'Customer discussed the following challenges:
1. Our analytics dashboards for our Tier 2 apps are taking too long to load.

Proposed PillarDB Standard as a solution to address these needs.', 'call', '2026-02-21T22:43:16', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13156, 4072, 2, 'Customer discussed the following challenges:
1. Batch jobs and analytics queries are running so long they interfere with daily operations.
2. Our security and monitoring stack (e.g., Splunk, Datadog) has no pre-built dashboard for this database.

Proposed TitanDB Enterprise as a solution to address these needs.', 'call', '2026-02-21T22:04:58', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13193, 4094, 1, 'Spoke with Michael Davis regarding their needs: Customer talked about the following challenges:
1. Our BI dashboards are too ''rigid.'' I can''t ''double-click'' and ''ask a follow-up question''.

Proposed OmniConnect Proxy as a solution to address these needs.', 'meeting', '2026-02-21T08:53:24', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13222, 4111, 1, 'Customer discussed the following challenges:
1. Only 5% of our company (the ''data team'') can actually access and analyze our data. It''s a bottleneck.

Proposed Converge Lakehouse as a solution to address these needs.', 'call', '2026-02-21T21:30:01', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13247, 3587, 1, 'Customer discussed the following challenges:
1. We need consistent training across our entire global team.

Proposed OS Guardian Support as a solution to address these needs.', 'meeting', '2026-02-21T22:38:58', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13274, 4143, 2, 'Follow-up with Robert Miller: Customer discussed the following challenges:
1. Adding a new shard to our cluster is a high-risk, manual process that can cause data inconsistencies.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-02-21T23:35:52', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13304, 2282, 1, 'Customer discussed the following challenges:
1. Our load balancer isn''t database-aware, so it keeps sending traffic to a node that is overloaded or in maintenance.
2. An attacker used a SQLi vulnerability to exfiltrate our entire customer list.

Proposed OmniConnect Proxy as a solution to address these needs.', 'email', '2026-02-21T19:23:43', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13333, 4169, 1, 'Call with Jane Johnson at Johnson Manufacturing Solutions: Customer discussed the following challenges:
1. We have no on-demand learning resources; all our training is ad-hoc and informal.

Proposed OS Guardian Support as a solution to address these needs.', 'email', '2026-02-21T17:44:33', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13354, 4177, 1, 'Call notes for Jones Technology Corp: Customer went over the following challenges:
1. Our internal tools are critical to our offeringivity, but they don''t get the same budget as customer-facing apps.

Proposed PillarDB Standard as a solution to address these needs.', 'meeting', '2026-02-21T22:49:12', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13362, 4181, 2, 'Customer discussed the following challenges:
1. By the time we''ve triaged the alerts and escalated to the right team, the incident has been going for 30 minutes.

Proposed Synapse AIOps as a solution to address these needs.', 'internal', '2026-02-21T23:57:30', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13473, 4242, 2, 'Customer discussed the following challenges:
1. We''re not finding new opportunities; we''re just reporting on what already happened.
2. We can''t run complex SQL queries on our streaming data; we can only do simple ''counts''.

Proposed Converge Lakehouse as a solution to address these needs.', 'internal', '2026-02-21T21:41:02', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13778, 4270, 1, 'First call with David Davis. They found us through a Retail conference. Main interest is solving We need to run our HR system on a database that is stable and has a vendor we can call.. Demo scheduled.', NULL, '2025-12-06T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13779, 4270, 1, 'Sent ROI calculator to David Davis.', NULL, '2026-01-04T06:47:03.121027', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13780, 4270, 1, 'Deep-dive meeting with Williams Education Group stakeholders. Key issue raised: We need to run our HR system on a database that is stable and has a vendor we can call.. They''ve tried other solutions but none addressed their Retail requirements. Good engagement from David Davis. They see the potential. Will prepare custom demo addressing We need to run our HR system on a database that is stable and has a vendor we can call..', NULL, '2026-01-18T04:55:46.168428', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13781, 4270, 1, 'Final technical review with David Davis and their team. Deep dive into We need to run our HR system on a database that is stable and has a vendor we can call. and Our data ingestion for our secondary applications is too slow.. Their current workaround is manual and error-prone. Positive vibes from the meeting. David Davis supportive. Scheduling closing call for end of week.', NULL, '2026-02-14T12:16:51.414387', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (13782, 4270, 1, 'Detailed technical discussion with Williams Education Group team. Key stakeholder: David Davis.

**Call Summary**
Deep technical conversation with Williams Education Group''s evaluation team. David Davis has done their homework on our platform. Discussion centered on Support on a Budget and how we address We need to run our HR system on a database that is stable and has a vendor we can call. better than their current solution.

**Target Use Cases**
Key use cases driving this evaluation at Williams Education Group:

1. **Support on a Budget**
   - Access our professional 8x5 business-hour support team for troubleshooting, bug resolution, and best-practice guidance. This provides a crucial safety net for your production systems at a cost-effective price, giving you expert help when you need it most without paying for 24/7 critical coverage.
   - This is their primary driver for evaluating PillarDB Standard. David Davis estimates this will save their team 15+ hours per week.
   - They''ve tried addressing this with their current solution but hit scaling limitations.

2. **Support for Tier 2 and 3 Applications**
   - Run your important but non-mission-critical applications, such as internal wikis, CMS platforms, or development/testing environments, on a reliable, vendor-backed database. You get professional support and stability without allocating your top-tier budget, ensuring these essential services remain healthy and performant.
   - Secondary priority but equally important for their long-term roadmap.
   - Would consolidate multiple point solutions they currently maintain.

**Why This Matters:** The Support on a Budget use case is specifically designed to solve We need to run our HR system on a database that is stable and has a vendor we can call. - the core issue David Davis raised in our first conversation.

_Deal: $52225 | Stage: close | Champion: David Davis_', NULL, '2026-03-04T09:17:18.427297', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14190, 4303, 1, 'Meeting confirmed for next week.', NULL, '2026-02-07T05:15:17.819125', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14191, 4303, 1, 'Comprehensive review session with Michael Miller regarding ClarityDB Guardian implementation.

**Call Summary**
Great session with Davis Healthcare Solutions team. They walked us through their Database Profiling requirements in detail. Clear alignment between their needs around We added an index, and it made other queries slower. and what ClarityDB Guardian delivers.

**Competitive Landscape**
Competition includes **Elastic** (incumbent) and **MongoDB** (also evaluating). We''re differentiated on:
- Native support for their Technology workflows
- More flexible pricing model
- Faster time to value

They had a bad experience with MongoDB previously - opportunity to capitalize.

_Deal: $40095 | Stage: early | Champion: Michael Miller_', NULL, '2026-02-07T10:56:14.564620', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14192, 4303, 1, 'Extended call with Michael Miller at Davis Healthcare Solutions covering their Technology infrastructure.

**Call Summary**
Productive discussion covering their Database Profiling requirements. Michael Miller led the conversation with clear priorities around solving We added an index, and it made other queries slower.. The team was engaged and asked detailed questions about how ClarityDB Guardian supports Get a granular, second-by-second breakdown of all database activity, including CPU, I/O, and wait events. This deep-dive profiling allows DBAs to pinpoint the exact internal bottlenecks that are limiting throughput, enabling precise, surgical tuning for maximum performance..

**Competitive Landscape**
Competition includes **Databricks** (incumbent) and **Snowflake** (also evaluating). We''re differentiated on:
- Native support for their Technology workflows
- More flexible pricing model
- Faster time to value

They had a bad experience with Snowflake previously - opportunity to capitalize.

_Deal: $40095 | Stage: early | Champion: Michael Miller_', NULL, '2026-02-08T07:09:13.745425', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14193, 4303, 1, 'Shared troubleshooting steps via email after support raised an issue.', NULL, '2026-02-08T21:24:48.362758', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14194, 4303, 1, 'Initial discovery call with Michael Miller at Davis Healthcare Solutions. They''re experiencing We added an index, and it made other queries slower.. Scheduled follow-up demo for next week to show how ClarityDB Guardian addresses this.', NULL, '2026-02-10T02:49:44.113435', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14195, 4303, 1, '## Meeting Notes: Davis Healthcare Solutions

Extended technical and business discussion with Michael Miller and their team at Davis Healthcare Solutions. This was a pivotal meeting in the evaluation process.

### Call Summary
Productive discussion covering their Database Profiling requirements. Michael Miller led the conversation with clear priorities around solving We added an index, and it made other queries slower.. The team was engaged and asked detailed questions about how ClarityDB Guardian supports Get a granular, second-by-second breakdown of all database activity, including CPU, I/O, and wait events. This deep-dive profiling allows DBAs to pinpoint the exact internal bottlenecks that are limiting throughput, enabling precise, surgical tuning for maximum performance..

### Target Use Cases
The Davis Healthcare Solutions team is targeting the following deployment scenarios:

1. **Database Profiling**
   - Get a granular, second-by-second breakdown of all database activity, including CPU, I/O, and wait events. This deep-dive profiling allows DBAs to pinpoint the exact internal bottlenecks that are limiting throughput, enabling precise, surgical tuning for maximum performance.
   - This is their primary driver for evaluating ClarityDB Guardian. Michael Miller estimates this will save their team 15+ hours per week.
   - They''ve tried addressing this with their current solution but hit scaling limitations.

2. **Troubleshooting Problems**
   - Leverage guided root-cause analysis to solve complex issues in minutes, not hours. Guardian''s historical profiler lets you "rewind time" to see exactly what was running during a past incident, identifying the blocking query or resource bottleneck that caused the problem.
   - Complements their primary use case. Once the first is running, this becomes the natural next step.
   - ROI calculations show significant cost savings here.

**Why This Matters:** The Database Profiling use case is specifically designed to solve We added an index, and it made other queries slower. - the core issue Michael Miller raised in our first conversation.

### Competitive Landscape
Davis Healthcare Solutions is also evaluating **MongoDB** and **Elastic**. Our key differentiators:
- Superior handling of We added an index, and it made other queries slower.
- Stronger Technology-specific features
- Better customer support reputation

Michael Miller mentioned they''ve had issues with MongoDB''s implementation complexity in the past.

### Timeline & Urgency
Michael Miller indicated a target decision date of end of quarter. Key timeline drivers:
- Current contract with existing vendor expires in 90 days
- New fiscal year budget available starting next month
- Technology priority initiative tied to this solution

**Risk:** Delay could push to next budget cycle.

### Pain Points Discussed
Key pain points identified during the discussion with Davis Healthcare Solutions:

1. **We added an index, and it made other queries slower.** - Impacting customer satisfaction and SLA compliance. They''ve had multiple incidents this quarter.
2. **Our dev/test database environments don''t match production, so our tests are meaningless.** - Related to the first issue. Solving one should help address the other.

Their current solution lacks the Technology-specific features they need. Been looking for alternatives for 6+ months.

---
**Deal Details:** $40095 ARR | **Stage:** early | **Industry:** Technology
**Champion:** Michael Miller | **Product:** ClarityDB Guardian', NULL, '2026-02-10T10:25:41.289691', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14196, 4303, 1, 'Technical deep-dive with Davis Healthcare Solutions''s engineering team. Good discussion on We added an index, and it made other queries slower. and Our dev/test database environments don''t match production, so our tests are meaningless.. Michael Miller asking for reference customers.', NULL, '2026-02-10T19:39:59.181043', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14197, 4303, 1, 'Added discovery session to calendar with Davis Healthcare Solutions.', NULL, '2026-02-10T22:16:37.590088', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14198, 4303, 1, 'Michael Miller is reviewing internally.', NULL, '2026-02-11T10:56:37.844828', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14199, 4303, 1, 'Called Michael Miller, went to voicemail.', NULL, '2026-02-12T23:36:18.909647', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14200, 4303, 1, 'Waiting for Davis Healthcare Solutions decision.', NULL, '2026-02-13T01:19:43.859550', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14201, 4303, 1, 'Extended call with Michael Miller at Davis Healthcare Solutions covering their Technology infrastructure.

**Call Summary**
Extended meeting covering both business and technical aspects. Michael Miller brought in their architect to validate our approach to Database Profiling. Strong interest in how we solve We added an index, and it made other queries slower. for Technology customers.

**Timeline & Urgency**
Michael Miller indicated a target decision date of end of quarter. Key timeline drivers:
- Current contract with existing vendor expires in 90 days
- New fiscal year budget available starting next month
- Technology priority initiative tied to this solution

**Risk:** Delay could push to next budget cycle.

_Deal: $40095 | Stage: middle | Champion: Michael Miller_', NULL, '2026-02-13T02:00:23.307580', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14202, 4303, 1, 'Noted competitor involvement; monitoring next steps.', NULL, '2026-02-15T03:52:35.861415', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14203, 4303, 1, 'Demo and technical discussion with Michael Miller''s team. Deep dive into We added an index, and it made other queries slower. and Our dev/test database environments don''t match production, so our tests are meaningless.. Their current workaround is manual and error-prone. Davis Healthcare Solutions team receptive to our approach. Building momentum. Will prepare custom demo addressing We added an index, and it made other queries slower..', NULL, '2026-02-15T19:48:22.728579', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14204, 4303, 1, 'Productive follow-up session with Davis Healthcare Solutions. Deep dive into We added an index, and it made other queries slower. and Our dev/test database environments don''t match production, so our tests are meaningless.. Their current workaround is manual and error-prone. Encouraging discussion. Next steps agreed upon. Scheduling reference call with similar Technology customer.', NULL, '2026-02-16T09:19:39.093337', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14205, 4303, 1, 'Contract review meeting with Davis Healthcare Solutions legal and Michael Miller. Minor redlines on SLA terms. Should close by end of month.', NULL, '2026-02-16T10:38:48.650002', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14206, 4303, 1, 'Contract and pricing discussion with Davis Healthcare Solutions. Main discussion centered on We added an index, and it made other queries slower.. Michael Miller mentioned this has been a pain point for over a year. High energy meeting - Michael Miller already talking implementation timeline. Next: Final contract review with legal teams.', NULL, '2026-02-17T03:40:56.414912', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14207, 4303, 1, 'Pre-decision meeting with Michael Miller and procurement. Deep dive into We added an index, and it made other queries slower. and Our dev/test database environments don''t match production, so our tests are meaningless.. Their current workaround is manual and error-prone. Excellent reception from the Davis Healthcare Solutions team. They see clear value. Preparing executive summary for their leadership.', NULL, '2026-02-17T18:13:02.663022', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14208, 4303, 1, 'Scheduled intro call with stakeholder.', NULL, '2026-02-18T04:04:43.938029', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14210, 4303, 1, 'Critical negotiation meeting with Davis Healthcare Solutions. The team is struggling with We added an index, and it made other queries slower., which is impacting their operations significantly. Michael Miller is very enthusiastic about ClarityDB Guardian. Strong champion potential. Will send revised pricing based on today''s discussion.', NULL, '2026-02-18T11:44:08.912432', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14211, 4303, 1, '## Call Summary: Davis Healthcare Solutions

Comprehensive review session covering all aspects of their Technology requirements. Multiple stakeholders present including Michael Miller.

### Call Summary
Extended meeting covering both business and technical aspects. Michael Miller brought in their architect to validate our approach to Database Profiling. Strong interest in how we solve We added an index, and it made other queries slower. for Technology customers.

### Technical Requirements
- **Primary:** We added an index, and it made other queries slower.
- **Secondary:** Our dev/test database environments don''t match production, so our tests are meaningless.
- CI/CD pipeline integration
- Container and Kubernetes support
- High availability (99.9%+ uptime requirement)

### Competitive Landscape
Competition includes **Databricks** (incumbent) and **Elastic** (also evaluating). We''re differentiated on:
- Native support for their Technology workflows
- More flexible pricing model
- Faster time to value

They had a bad experience with Elastic previously - opportunity to capitalize.

### Next Steps
1. Send final proposal with negotiated terms
2. Schedule contract review with Davis Healthcare Solutions''s legal team
3. Prepare implementation timeline and resource plan
4. Michael Miller to get final budget approval from leadership
5. Target close date: End of month

---
**Deal Details:** $40095 ARR | **Stage:** late | **Industry:** Technology
**Champion:** Michael Miller | **Product:** ClarityDB Guardian', NULL, '2026-02-19T10:19:37.781577', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14212, 4303, 1, 'Email bounced - need updated contact info.', NULL, '2026-02-19T17:12:49.601289', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14213, 4303, 1, 'Technical review completed.', NULL, '2026-02-20T19:05:52.340657', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14214, 4303, 1, 'Comprehensive review session with Michael Miller regarding ClarityDB Guardian implementation.

**Call Summary**
Great session with Davis Healthcare Solutions team. They walked us through their Database Profiling requirements in detail. Clear alignment between their needs around We added an index, and it made other queries slower. and what ClarityDB Guardian delivers.

**Key Stakeholders**
- **Michael Miller** (Primary Contact) - Solutions Architect, strong champion, driving the evaluation
- **David** - Chief Architect, technical decision maker, needs to sign off on architecture
- **Mike** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the VP of Engineering. Michael Miller has direct access and influence.

**Technical Requirements**
- **Primary:** We added an index, and it made other queries slower.
- **Secondary:** Our dev/test database environments don''t match production, so our tests are meaningless.
- CI/CD pipeline integration
- Container and Kubernetes support
- Audit logging and compliance reporting

_Deal: $40095 | Stage: close | Champion: Michael Miller_', NULL, '2026-02-21T23:37:35.331799', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14215, 4303, 1, 'Comprehensive review session with Michael Miller regarding ClarityDB Guardian implementation.

**Call Summary**
Productive discussion covering their Database Profiling requirements. Michael Miller led the conversation with clear priorities around solving We added an index, and it made other queries slower.. The team was engaged and asked detailed questions about how ClarityDB Guardian supports Get a granular, second-by-second breakdown of all database activity, including CPU, I/O, and wait events. This deep-dive profiling allows DBAs to pinpoint the exact internal bottlenecks that are limiting throughput, enabling precise, surgical tuning for maximum performance..

**Target Use Cases**
Key use cases driving this evaluation at Davis Healthcare Solutions:

1. **Database Profiling**
   - Get a granular, second-by-second breakdown of all database activity, including CPU, I/O, and wait events. This deep-dive profiling allows DBAs to pinpoint the exact internal bottlenecks that are limiting throughput, enabling precise, surgical tuning for maximum performance.
   - Tied to a strategic initiative from their leadership. Must be in place by end of quarter.
   - Michael Miller confirmed budget is allocated specifically for this use case.

2. **Troubleshooting Problems**
   - Leverage guided root-cause analysis to solve complex issues in minutes, not hours. Guardian''s historical profiler lets you "rewind time" to see exactly what was running during a past incident, identifying the blocking query or resource bottleneck that caused the problem.
   - Complements their primary use case. Once the first is running, this becomes the natural next step.
   - ROI calculations show significant cost savings here.

**Why This Matters:** The Database Profiling use case is specifically designed to solve We added an index, and it made other queries slower. - the core issue Michael Miller raised in our first conversation.

**Next Steps**
1. Follow up with additional materials requested
2. Schedule next call with Michael Miller
3. Send meeting summary and action items

_Deal: $40095 | Stage: close | Champion: Michael Miller_', NULL, '2026-02-21T23:37:35.331799', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14534, 2887, 2, 'Spoke with Michael Smith regarding their needs: Customer reviewed the following challenges:
1. We want AI to ''read'' all our customer support tickets and tell us ''what are the top 3 complaints this week?''
2. Our AI team is in a ''silo.'' They''re building models, but the business doesn''t understand them or use them.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-02-21T23:39:47', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14671, 4338, 2, 'Extended call with David Johnson at Smith Healthcare Solutions covering their Manufacturing infrastructure.

**Call Summary**
Deep technical conversation with Smith Healthcare Solutions''s evaluation team. David Johnson has done their homework on our platform. Discussion centered on data management challenges and how we compare to their current solution.

**Pain Points Discussed**
David Johnson outlined the issues they''re facing with their current approach:


Budget has been allocated for this initiative. They need a solution in place before end of fiscal year.

**Target Use Cases**
David Johnson outlined specific use cases they want to address with Synapse AIOps:


_Deal: $53461 | Stage: early | Champion: David Johnson_', NULL, '2026-01-28T04:24:49.155763', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14672, 4338, 2, 'Detailed technical discussion with Smith Healthcare Solutions team. Key stakeholder: David Johnson.

**Call Summary**
Extended meeting covering both business and technical aspects. David Johnson brought in their architect to validate our approach to data management challenges. Strong interest in our Manufacturing experience.

**Next Steps**
1. Prepare custom demo addressing key requirements
2. Schedule reference call with similar Manufacturing customer
3. Send preliminary pricing and packaging options
4. David Johnson to arrange meeting with their VP of Engineering

_Deal: $53461 | Stage: middle | Champion: David Johnson_', NULL, '2026-02-17T08:51:01.745022', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14673, 4338, 2, 'Left voicemail requesting updated purchase timeline.', NULL, '2026-03-25T07:18:11.675671', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14674, 4338, 2, 'Sent quote to Smith Healthcare Solutions.', NULL, '2026-04-22T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14818, 1292, 1, 'Customer discussed the following challenges:
1. Our IT ''knowledge base'' is a black hole; no one can find anything.
2. We want to build a Slackbot to ''start the staging server,'' but no one knows how.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-02-21T19:18:44', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (14953, 1952, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'call', '2026-02-21T16:17:03', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (15154, 4483, 1, 'Had our first substantive call with Johnson Finance Inc today. Main discussion centered on data management challenges. John Johnson mentioned this has been a pain point for over a year. Meeting went as expected. Following standard sales process. Will send POC proposal for their review.', NULL, '2025-12-28T04:00:58.009238', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (15155, 4483, 1, 'Continued evaluation discussions with John Johnson. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Education requirements. Standard evaluation process. Johnson Finance Inc doing due diligence. Scheduling reference call with similar Education customer.', NULL, '2026-01-04T05:11:14.467468', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (15156, 4483, 1, '## Technical Deep-Dive: Johnson Finance Inc

Detailed walkthrough of TitanDB Enterprise capabilities with Johnson Finance Inc''s engineering and business teams. Covered architecture, integration, and roadmap.

### Call Summary
Comprehensive call with John Johnson and two other stakeholders from their technical team. Main focus was understanding how TitanDB Enterprise handles data management challenges. Good energy throughout the session.

### Technical Requirements
- Enterprise-grade security
- 24/7 support availability
- Multi-region deployment support

### Competitive Landscape
This is a competitive deal. **Competitor A** has existing relationship but John Johnson frustrated with their roadmap. **Competitor B** in the mix but lacks Education expertise.

Our advantages: technical depth, Education focus, and John Johnson as a strong champion.

### Pain Points Discussed
The Johnson Finance Inc team highlighted several critical challenges:


Budget has been allocated for this initiative. They need a solution in place before end of fiscal year.

---
**Deal Details:** $53461 ARR | **Stage:** middle | **Industry:** Education
**Champion:** John Johnson | **Product:** TitanDB Enterprise', NULL, '2026-01-27T11:15:35.316954', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (15157, 4483, 1, 'Sent polite follow-up email with two calendar options to John Johnson.', NULL, '2026-02-03T12:45:30.293884', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (15158, 4483, 1, 'Demo went well with Johnson Finance Inc.', NULL, '2026-02-20T03:44:06.228163', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16156, 4556, 2, 'Kicked off the evaluation process with Smith Retail Solutions. The team is struggling with We need a ''single source of truth,'' not 10 different copies of our data., which is impacting their operations significantly. Lisa Davis engaged throughout the discussion. Setting up intro call with our solutions architect.', NULL, '2025-12-17T13:18:50.240598', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16157, 4556, 2, 'Had our first substantive call with Smith Retail Solutions today. Deep dive into We need a ''single source of truth,'' not 10 different copies of our data. and We need a central ''data catalog'' for all our assets, from database tables to CSV files.. Their current workaround is manual and error-prone. Meeting went as expected. Following standard sales process. Next: Schedule technical demo with their engineering team.', NULL, '2025-12-20T22:00:19.744840', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16158, 4556, 2, 'Proposal sent to Smith Retail Solutions.', NULL, '2026-01-03T17:00:00.167040', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16159, 4556, 2, 'Discovery session with Smith Retail Solutions team. Primary pain point is We need a ''single source of truth,'' not 10 different copies of our data.. Lisa Davis to loop in their technical lead for deeper dive.', NULL, '2026-01-08T05:05:51.822313', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16160, 4556, 2, 'Shared updated quote with revised terms for Smith Retail Solutions.', NULL, '2026-01-12T00:06:02.211562', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16161, 4556, 2, 'Follow-up scheduled with Lisa Davis.', NULL, '2026-01-16T07:23:36.927468', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16162, 4556, 2, 'Technical deep-dive with Smith Retail Solutions''s engineering team. Good discussion on We need a ''single source of truth,'' not 10 different copies of our data. and We need a central ''data catalog'' for all our assets, from database tables to CSV files.. Lisa Davis asking for reference customers.', NULL, '2026-01-29T04:34:29.832981', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16163, 4556, 2, 'Updated opportunity stage after internal discussion.', NULL, '2026-02-05T12:06:01.823879', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16164, 4556, 2, 'Productive session with Smith Retail Solutions. Walked through architecture for handling We need a ''single source of truth,'' not 10 different copies of our data.. Lisa Davis impressed with our Healthcare experience.', NULL, '2026-02-05T12:09:50.297339', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16165, 4556, 2, 'Uploaded technical spec requested by Lisa Davis.', NULL, '2026-02-10T16:57:36.122587', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16166, 4556, 2, 'Technical review completed.', NULL, '2026-02-17T03:33:35.790650', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16167, 4556, 2, 'Detailed technical discussion with Smith Retail Solutions team. Key stakeholder: Lisa Davis.

**Call Summary**
Productive discussion covering their Real-time Analytics requirements. Lisa Davis led the conversation with clear priorities around solving We need a ''single source of truth,'' not 10 different copies of our data.. The team was engaged and asked detailed questions about how Converge Lakehouse supports Ingest and query streaming data from IoT devices or application clickstreams in near real-time. This enables you to build live dashboards that monitor business operations, detect fraud as it happens, or provide real-time personalization, giving you a significant competitive advantage..

**Competitive Landscape**
Smith Retail Solutions is also evaluating **Veeva** and **Epic**. Our key differentiators:
- Superior handling of We need a ''single source of truth,'' not 10 different copies of our data.
- Stronger Healthcare-specific features
- Better customer support reputation

Lisa Davis mentioned they''ve had issues with Veeva''s implementation complexity in the past.

_Deal: $34054 | Stage: late | Champion: Lisa Davis_', NULL, '2026-02-23T10:33:04.108399', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16168, 4556, 2, 'Detailed technical discussion with Smith Retail Solutions team. Key stakeholder: Lisa Davis.

**Call Summary**
Deep technical conversation with Smith Retail Solutions''s evaluation team. Lisa Davis has done their homework on our platform. Discussion centered on Real-time Analytics and how we address We need a ''single source of truth,'' not 10 different copies of our data. better than their current solution.

**Pain Points Discussed**
Key pain points identified during the discussion with Smith Retail Solutions:

1. **We need a ''single source of truth,'' not 10 different copies of our data.** - This has been causing significant operational overhead. Lisa Davis mentioned their team spends 20+ hours/week on manual workarounds.
2. **We need a central ''data catalog'' for all our assets, from database tables to CSV files.** - Secondary but growing concern. They anticipate this becoming critical in Q3.

Budget has been allocated for this initiative. They need a solution in place before end of fiscal year.

_Deal: $34054 | Stage: late | Champion: Lisa Davis_', NULL, '2026-03-04T10:18:41.023818', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16169, 4556, 2, 'Left request to call back after internal review.', NULL, '2026-03-08T06:54:57.298174', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16170, 4556, 2, 'Sent quote to Smith Retail Solutions.', NULL, '2026-03-12T10:05:07.838506', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16174, 4558, 2, 'Good call with John Garcia today.', NULL, '2026-01-04T18:26:03.741298', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16175, 4558, 2, 'Kicked off the evaluation process with Garcia Finance Systems. Key issue raised: We have no ''human-in-the-loop'' or ''approval'' process for AI-driven decisions.. They''ve tried other solutions but none addressed their Manufacturing requirements. John Garcia engaged throughout the discussion. Will send POC proposal for their review.', NULL, '2026-01-06T10:58:45.556641', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16176, 4558, 2, 'Extended call with John Garcia at Garcia Finance Systems covering their Manufacturing infrastructure.

**Call Summary**
Extended meeting covering both business and technical aspects. John Garcia brought in their architect to validate our approach to AI Governance. Strong interest in how we solve We have no ''human-in-the-loop'' or ''approval'' process for AI-driven decisions. for Manufacturing customers.

**Key Stakeholders**
- **John Garcia** (Primary Contact) - Solutions Architect, strong champion, driving the evaluation
- **Lisa** - Chief Architect, technical decision maker, needs to sign off on architecture
- **Jennifer** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the Chief Architect. John Garcia has direct access and influence.

**Timeline & Urgency**
John Garcia mentioned several timing factors:
- Board meeting next month where they need to present solution
- Integration with their Q2 product launch
- Team capacity available now, may not be later

Urgency is real. We should accelerate our response.

_Deal: $35726 | Stage: early | Champion: John Garcia_', NULL, '2026-01-10T05:46:06.665723', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16177, 4558, 2, 'Shared SOW draft with Garcia Finance Systems for review.', NULL, '2026-01-11T13:56:36.026406', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16178, 4558, 2, 'Discovery session with Garcia Finance Systems team. Primary pain point is We have no ''human-in-the-loop'' or ''approval'' process for AI-driven decisions.. John Garcia to loop in their technical lead for deeper dive.', NULL, '2026-01-14T19:05:49.449574', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16179, 4558, 2, 'Demo went well with Garcia Finance Systems. John Garcia was engaged, especially around the We have no ''human-in-the-loop'' or ''approval'' process for AI-driven decisions. solution. They want to see a POC proposal.', NULL, '2026-01-21T22:49:42.795331', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16180, 4558, 2, 'Demo and technical discussion with John Garcia''s team. Deep dive into We have no ''human-in-the-loop'' or ''approval'' process for AI-driven decisions. and Our ''AI'' app is a ''black box.'' We have no idea why it made a specific decision.. Their current workaround is manual and error-prone. John Garcia engaged throughout the discussion. Scheduling reference call with similar Manufacturing customer.', NULL, '2026-01-29T20:38:10.663183', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16181, 4558, 2, 'Productive session with Garcia Finance Systems. Walked through architecture for handling We have no ''human-in-the-loop'' or ''approval'' process for AI-driven decisions.. John Garcia impressed with our Manufacturing experience.', NULL, '2026-02-07T13:59:23.149456', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16182, 4558, 2, 'Comprehensive review session with John Garcia regarding Prometheus AI Factory implementation.

**Call Summary**
Productive discussion covering their AI Governance requirements. John Garcia led the conversation with clear priorities around solving We have no ''human-in-the-loop'' or ''approval'' process for AI-driven decisions.. The team was engaged and asked detailed questions about how Prometheus AI Factory supports Utilize a central control plane to manage the entire lifecycle of your AI models, from development to production. This includes tracking model lineage, managing access permissions, and auditing all AI-driven decisions, providing the robust governance and explainability that regulators now demand..

**Pain Points Discussed**
John Garcia outlined the issues they''re facing with their current approach:

1. **We have no ''human-in-the-loop'' or ''approval'' process for AI-driven decisions.** - Impacting customer satisfaction and SLA compliance. They''ve had multiple incidents this quarter.
2. **Our ''AI'' app is a ''black box.'' We have no idea why it made a specific decision.** - Secondary but growing concern. They anticipate this becoming critical in Q3.

John Garcia emphasized that solving these issues is a top priority for their leadership team.

_Deal: $35726 | Stage: middle | Champion: John Garcia_', NULL, '2026-02-10T15:41:32.100239', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16183, 4558, 2, 'Deep-dive meeting with Garcia Finance Systems stakeholders. The team is struggling with We have no ''human-in-the-loop'' or ''approval'' process for AI-driven decisions., which is impacting their operations significantly. John Garcia professional and thorough in their questions. Scheduling reference call with similar Manufacturing customer.', NULL, '2026-02-14T09:09:16.731961', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16184, 4558, 2, 'Positive feedback from Garcia Finance Systems team.', NULL, '2026-02-18T07:57:23.307655', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16185, 4558, 2, 'Detailed technical discussion with Garcia Finance Systems team. Key stakeholder: John Garcia.

**Call Summary**
Great session with Garcia Finance Systems team. They walked us through their AI Governance requirements in detail. Clear alignment between their needs around We have no ''human-in-the-loop'' or ''approval'' process for AI-driven decisions. and what Prometheus AI Factory delivers.

**Competitive Landscape**
This is a competitive deal. **PTC** has existing relationship but John Garcia frustrated with their roadmap. **Rockwell** in the mix but lacks Manufacturing expertise.

Our advantages: technical depth, Manufacturing focus, and John Garcia as a strong champion.

_Deal: $35726 | Stage: middle | Champion: John Garcia_', NULL, '2026-02-20T07:24:39.856740', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16186, 4558, 2, 'Left VM for John Garcia.', NULL, '2026-02-23T16:51:50.048055', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16187, 4558, 2, 'John Garcia OOO until Monday.', NULL, '2026-02-27T17:13:27.051772', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16188, 4558, 2, 'John Garcia to call back tomorrow.', NULL, '2026-03-05T05:29:52.467931', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16189, 4558, 2, 'Waiting for updated requirements from the project team.', NULL, '2026-03-09T00:09:50.581737', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16190, 4558, 2, 'Waiting on finance team to approve the revised payment terms.', NULL, '2026-03-14T23:17:30.355598', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16191, 4558, 2, 'Pricing discussion with John Garcia. Deal size around $35726. They''re comparing us to two other vendors. Decision expected in 2 weeks.', NULL, '2026-03-24T05:06:41.014260', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16192, 4558, 2, 'Sync with John Garcia. They''re working through We have no ''human-in-the-loop'' or ''approval'' process for AI-driven decisions. challenges. Prometheus AI Factory well-positioned to help.', NULL, '2026-03-24T05:49:36.394366', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16193, 4558, 2, 'Meeting with Garcia Finance Systems team went well. John Garcia is our champion, pushing internally. Deal progressing.', NULL, '2026-04-01T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16536, 1466, 1, 'Customer discussed the following challenges:
1. Our automation tools are all ''IT-focused.'' They can''t talk to our business apps like Workday or SAP.
2. Our on-call engineer gets an alert on their phone, but they can''t do anything about it until they get to their laptop.

Proposed Synapse AIOps as a solution to address these needs. Will follow up with Jane Davis next week.', 'internal', '2026-02-21T09:55:35', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16550, 4684, 2, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'internal', '2026-02-21T18:44:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16563, 3185, 1, 'Client discussed the following challenges:
1. Our team is skilled in other databases, but not this one, and we''re making ''rookie'' mistakes.
2. We keep ''rediscovering'' solutions to problems our team has already solved.

Proposed OS Guardian Support as a solution to address these needs.', 'internal', '2026-02-21T20:21:56', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16946, 4731, 2, 'Introductory call with Emily Miller to understand their needs. Main discussion centered on We have no way to compare the schema in ''dev'' vs. ''prod'' to see what''s different.. Emily Miller mentioned this has been a pain point for over a year. Emily Miller professional and thorough in their questions. Will send POC proposal for their review.', NULL, '2026-02-08T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16947, 4731, 2, 'No update - following normal timeline.', NULL, '2026-02-09T05:22:47.281326', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16948, 4731, 2, 'Emily Miller is reviewing internally.', NULL, '2026-02-09T07:21:00.810185', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16949, 4731, 2, 'Kicked off the evaluation process with Garcia Manufacturing Co. The team is struggling with We have no way to compare the schema in ''dev'' vs. ''prod'' to see what''s different., which is impacting their operations significantly. Emily Miller professional and thorough in their questions. Will send POC proposal for their review.', NULL, '2026-02-09T23:41:15.063479', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16950, 4731, 2, 'Had our first substantive call with Garcia Manufacturing Co today. The team is struggling with We have no way to compare the schema in ''dev'' vs. ''prod'' to see what''s different., which is impacting their operations significantly. Emily Miller engaged throughout the discussion. Setting up intro call with our solutions architect.', NULL, '2026-02-11T15:13:57.093623', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16951, 4731, 2, 'Sent quote to Garcia Manufacturing Co.', NULL, '2026-02-12T08:28:02.137143', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16952, 4731, 2, 'Waiting for Emily Miller to call back with budget approval.', NULL, '2026-02-13T05:22:36.703171', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16953, 4731, 2, 'Positive feedback from Garcia Manufacturing Co team.', NULL, '2026-02-13T05:23:17.341676', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16954, 4731, 2, 'Emily Miller is reviewing internally.', NULL, '2026-02-14T03:06:44.392328', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16955, 4731, 2, 'Demo went well with Garcia Manufacturing Co. Emily Miller was engaged, especially around the We have no way to compare the schema in ''dev'' vs. ''prod'' to see what''s different. solution. They want to see a POC proposal.', NULL, '2026-02-16T01:57:05.863949', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16957, 4731, 2, 'Detailed technical discussion with Garcia Manufacturing Co team. Key stakeholder: Emily Miller.

**Call Summary**
Extended meeting covering both business and technical aspects. Emily Miller brought in their architect to validate our approach to Data Engineering. Strong interest in how we solve We have no way to compare the schema in ''dev'' vs. ''prod'' to see what''s different. for Education customers.

**Next Steps**
1. Prepare custom demo addressing We have no way to compare the schema in ''dev'' vs. ''prod'' to see what''s different.
2. Schedule reference call with similar Education customer
3. Send preliminary pricing and packaging options
4. Emily Miller to arrange meeting with their VP of Engineering

_Deal: $62194 | Stage: middle | Champion: Emily Miller_', NULL, '2026-02-16T05:05:33.006370', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16958, 4731, 2, 'Emailed renewal options for Garcia Manufacturing Co.', NULL, '2026-02-16T07:02:57.336800', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16959, 4731, 2, 'Comprehensive review session with Emily Miller regarding CodeCraft DevKit implementation.

**Call Summary**
Great session with Garcia Manufacturing Co team. They walked us through their Data Engineering requirements in detail. Clear alignment between their needs around We have no way to compare the schema in ''dev'' vs. ''prod'' to see what''s different. and what CodeCraft DevKit delivers.

**Key Stakeholders**
- **Emily Miller** (Primary Contact) - Platform Director, strong champion, driving the evaluation
- **Amanda** - Head of Platform, technical decision maker, needs to sign off on architecture
- **Chris** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the Director of IT. Emily Miller has direct access and influence.

_Deal: $62194 | Stage: late | Champion: Emily Miller_', NULL, '2026-02-18T14:59:15.318748', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16960, 4731, 2, 'Waiting on Garcia Manufacturing Co decision.', NULL, '2026-02-18T18:14:04.571612', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16961, 4731, 2, 'Confirmed stakeholder kickoff meeting for CodeCraft DevKit rollout.', NULL, '2026-02-20T11:44:01.550646', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16963, 4731, 2, 'Pre-decision meeting with Emily Miller and procurement. The team is struggling with We have no way to compare the schema in ''dev'' vs. ''prod'' to see what''s different., which is impacting their operations significantly. Emily Miller is very enthusiastic about CodeCraft DevKit. Strong champion potential. Will send revised pricing based on today''s discussion.', NULL, '2026-02-21T02:21:46.946471', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16964, 4731, 2, 'Waiting on final approval from finance.', NULL, '2026-02-21T14:04:22.042587', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (16965, 4731, 2, 'Positive feedback from Garcia Manufacturing Co team.', NULL, '2026-02-21T14:09:35.238791', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17003, 4735, 1, 'Introductory call with Michael Williams to understand their needs. Key issue raised: Connection storms during a restart or deployment regularly cause site-wide outages.. They''ve tried other solutions but none addressed their Finance requirements. Michael Williams professional and thorough in their questions. Setting up intro call with our solutions architect.', NULL, '2026-01-01T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17004, 4735, 1, 'Demo and technical discussion with Michael Williams''s team. Key issue raised: Connection storms during a restart or deployment regularly cause site-wide outages.. They''ve tried other solutions but none addressed their Finance requirements. Encouraging discussion. Next steps agreed upon. Will prepare custom demo addressing Connection storms during a restart or deployment regularly cause site-wide outages..', NULL, '2026-02-21T13:05:29.642253', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17005, 4735, 1, 'Sync with Michael Williams. They''re working through Connection storms during a restart or deployment regularly cause site-wide outages. challenges. OmniConnect Proxy well-positioned to help.', NULL, '2026-04-01T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17169, 4750, 2, 'Proposal sent to Smith Education LLC.', NULL, '2025-11-26T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17170, 4750, 2, 'Quick check-in - all on track.', NULL, '2025-12-01T23:22:28.088037', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17171, 4750, 2, 'First call with David Williams. They found us through a Healthcare conference. Main interest is solving Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.. Demo scheduled.', NULL, '2025-12-02T03:12:30.093385', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17172, 4750, 2, 'Initial discovery call with David Williams at Smith Education LLC. They''re experiencing Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.. Scheduled follow-up demo for next week to show how Prometheus AI Factory addresses this.', NULL, '2025-12-04T07:17:43.958362', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17173, 4750, 2, 'Extended call with David Williams at Smith Education LLC covering their Healthcare infrastructure.

**Call Summary**
Productive discussion covering their Data-Ready AI requirements. David Williams led the conversation with clear priorities around solving Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.. The team was engaged and asked detailed questions about how Prometheus AI Factory supports Leverage integrated data pipelines to automatically clean, transform, and feed your enterprise data into your AI models. This ensures your models are always trained on the freshest, highest-quality data, leading to more accurate and reliable AI-driven insights and automations..

**Pain Points Discussed**
The Smith Education LLC team highlighted several critical challenges:

1. **Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.** - Impacting customer satisfaction and SLA compliance. They''ve had multiple incidents this quarter.
2. **Our data scientists are spending all their time doing ''data cleaning'' and ''data prep''.** - Related to the first issue. Solving one should help address the other.

David Williams emphasized that solving these issues is a top priority for their leadership team.

**Competitive Landscape**
Competition includes **Medidata** (incumbent) and **Epic** (also evaluating). We''re differentiated on:
- Native support for their Healthcare workflows
- More flexible pricing model
- Faster time to value

They had a bad experience with Epic previously - opportunity to capitalize.

_Deal: $22541 | Stage: early | Champion: David Williams_', NULL, '2025-12-07T23:57:11.572744', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17174, 4750, 2, 'Detailed technical discussion with Smith Education LLC team. Key stakeholder: David Williams.

**Call Summary**
Great session with Smith Education LLC team. They walked us through their Data-Ready AI requirements in detail. Clear alignment between their needs around Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI. and what Prometheus AI Factory delivers.

**Target Use Cases**
Key use cases driving this evaluation at Smith Education LLC:

1. **Data-Ready AI**
   - Leverage integrated data pipelines to automatically clean, transform, and feed your enterprise data into your AI models. This ensures your models are always trained on the freshest, highest-quality data, leading to more accurate and reliable AI-driven insights and automations.
   - This is their primary driver for evaluating Prometheus AI Factory. David Williams estimates this will save their team 15+ hours per week.
   - They''ve tried addressing this with their current solution but hit scaling limitations.

2. **Secure AI Infrastructure**
   - Run your AI workloads on a hardened, pre-configured platform that includes security, monitoring, and networking by default. This eliminates the complexity of building a secure AI stack from scratch and ensures your powerful models are protected from unauthorized access or misuse.
   - Secondary priority but equally important for their long-term roadmap.
   - Would consolidate multiple point solutions they currently maintain.

**Connection to Pain Points:** Successfully implementing Data-Ready AI would directly address Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI., which is their biggest operational challenge.

_Deal: $22541 | Stage: early | Champion: David Williams_', NULL, '2025-12-08T12:27:40.201244', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17175, 4750, 2, 'Escalated pricing exception to regional manager.', NULL, '2025-12-13T01:49:19.236713', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17176, 4750, 2, 'Positive feedback from Smith Education LLC team.', NULL, '2025-12-21T10:01:05.846373', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17177, 4750, 2, 'Scheduled technical deep-dive with SE and David Williams.', NULL, '2025-12-23T18:53:57.728951', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17178, 4750, 2, 'Deep-dive meeting with Smith Education LLC stakeholders. Main discussion centered on Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.. David Williams mentioned this has been a pain point for over a year. Positive vibes from the meeting. David Williams supportive. Scheduling reference call with similar Healthcare customer.', NULL, '2025-12-28T22:05:45.431998', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17179, 4750, 2, 'Demo and technical discussion with David Williams''s team. Main discussion centered on Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.. David Williams mentioned this has been a pain point for over a year. Good engagement from David Williams. They see the potential. Following up with technical architecture document.', NULL, '2026-01-02T03:47:24.864663', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17180, 4750, 2, 'Productive follow-up session with Smith Education LLC. Key issue raised: Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.. They''ve tried other solutions but none addressed their Healthcare requirements. Smith Education LLC team receptive to our approach. Building momentum. Scheduling reference call with similar Healthcare customer.', NULL, '2026-01-02T21:05:17.104127', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17181, 4750, 2, '## Technical Deep-Dive: Smith Education LLC

Detailed walkthrough of Prometheus AI Factory capabilities with Smith Education LLC''s engineering and business teams. Covered architecture, integration, and roadmap.

### Call Summary
Extended meeting covering both business and technical aspects. David Williams brought in their architect to validate our approach to Data-Ready AI. Strong interest in how we solve Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI. for Healthcare customers.

### Competitive Landscape
This is a competitive deal. **Epic** has existing relationship but David Williams frustrated with their roadmap. **Veeva** in the mix but lacks Healthcare expertise.

Our advantages: technical depth, Healthcare focus, and David Williams as a strong champion.

### Pain Points Discussed
David Williams outlined the issues they''re facing with their current approach:

1. **Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.** - Critical blocker for their growth plans. Current solution can''t scale to meet demand.
2. **Our data scientists are spending all their time doing ''data cleaning'' and ''data prep''.** - Related to the first issue. Solving one should help address the other.

Their current solution lacks the Healthcare-specific features they need. Been looking for alternatives for 6+ months.

### Technical Requirements
- **Primary:** Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.
- **Secondary:** Our data scientists are spending all their time doing ''data cleaning'' and ''data prep''.
- HIPAA compliance certification
- HL7/FHIR integration support
- High availability (99.9%+ uptime requirement)

### Key Stakeholders
- **David Williams** (Primary Contact) - Solutions Architect, strong champion, driving the evaluation
- **Amanda** - CTO, technical decision maker, needs to sign off on architecture
- **Jennifer** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the VP of Engineering. David Williams has direct access and influence.

---
**Deal Details:** $22541 ARR | **Stage:** middle | **Industry:** Healthcare
**Champion:** David Williams | **Product:** Prometheus AI Factory', NULL, '2026-01-07T13:40:32.120428', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17182, 4750, 2, 'Detailed technical discussion with Smith Education LLC team. Key stakeholder: David Williams.

**Call Summary**
Comprehensive call with David Williams and two other stakeholders from their technical team. Main focus was understanding how Prometheus AI Factory handles Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI. in the context of their Data-Ready AI initiative. Good energy throughout the session.

**Key Stakeholders**
- **David Williams** (Primary Contact) - Platform Director, strong champion, driving the evaluation
- **Amanda** - VP of Engineering, technical decision maker, needs to sign off on architecture
- **Lisa** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the Director of IT. David Williams has direct access and influence.

**Technical Requirements**
- **Primary:** Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.
- **Secondary:** Our data scientists are spending all their time doing ''data cleaning'' and ''data prep''.
- HIPAA compliance certification
- HL7/FHIR integration support
- Multi-region deployment support

_Deal: $22541 | Stage: middle | Champion: David Williams_', NULL, '2026-01-14T19:01:45.963067', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17183, 4750, 2, 'Sent follow-up email - no response yet.', NULL, '2026-01-21T00:00:19.118941', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17184, 4750, 2, 'Pre-decision meeting with David Williams and procurement. The team is struggling with Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI., which is impacting their operations significantly. Very positive signals. Smith Education LLC team aligned on moving forward. Scheduling closing call for end of week.', NULL, '2026-01-23T15:22:20.273655', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17185, 4750, 2, 'Forwarded case study to David Williams.', NULL, '2026-01-28T00:18:05.724099', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17186, 4750, 2, 'Final technical review with David Williams and their team. Deep dive into Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI. and Our data scientists are spending all their time doing ''data cleaning'' and ''data prep''.. Their current workaround is manual and error-prone. High energy meeting - David Williams already talking implementation timeline. Scheduling closing call for end of week.', NULL, '2026-01-28T11:33:05.594532', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17187, 4750, 2, 'Left VM for David Williams at Smith Education LLC.', NULL, '2026-02-03T12:08:56.631280', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17188, 4750, 2, 'Negotiation call with David Williams and their procurement. Working through volume discount structure for $22541 deal.', NULL, '2026-02-08T06:00:48.923412', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17189, 4750, 2, 'Contract review meeting with Smith Education LLC legal and David Williams. Minor redlines on SLA terms. Should close by end of month.', NULL, '2026-02-08T18:45:05.085955', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17190, 4750, 2, 'Brief touch base with David Williams.', NULL, '2026-02-15T16:20:23.615768', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17191, 4750, 2, 'Extended call with David Williams at Smith Education LLC covering their Healthcare infrastructure.

**Call Summary**
Productive discussion covering their Data-Ready AI requirements. David Williams led the conversation with clear priorities around solving Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.. The team was engaged and asked detailed questions about how Prometheus AI Factory supports Leverage integrated data pipelines to automatically clean, transform, and feed your enterprise data into your AI models. This ensures your models are always trained on the freshest, highest-quality data, leading to more accurate and reliable AI-driven insights and automations..

**Technical Requirements**
- **Primary:** Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.
- **Secondary:** Our data scientists are spending all their time doing ''data cleaning'' and ''data prep''.
- HIPAA compliance certification
- HL7/FHIR integration support
- Integration with existing authentication systems (SSO/SAML)

**Target Use Cases**
Key use cases driving this evaluation at Smith Education LLC:

1. **Data-Ready AI**
   - Leverage integrated data pipelines to automatically clean, transform, and feed your enterprise data into your AI models. This ensures your models are always trained on the freshest, highest-quality data, leading to more accurate and reliable AI-driven insights and automations.
   - Tied to a strategic initiative from their leadership. Must be in place by end of quarter.
   - David Williams confirmed budget is allocated specifically for this use case.

2. **Secure AI Infrastructure**
   - Run your AI workloads on a hardened, pre-configured platform that includes security, monitoring, and networking by default. This eliminates the complexity of building a secure AI stack from scratch and ensures your powerful models are protected from unauthorized access or misuse.
   - Complements their primary use case. Once the first is running, this becomes the natural next step.
   - ROI calculations show significant cost savings here.

**Connection to Pain Points:** Successfully implementing Data-Ready AI would directly address Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI., which is their biggest operational challenge.

_Deal: $22541 | Stage: close | Champion: David Williams_', NULL, '2026-02-16T19:13:07.602915', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17192, 4750, 2, 'Sync with David Williams. They''re working through Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI. challenges. Prometheus AI Factory well-positioned to help.', NULL, '2026-02-18T13:47:19.921893', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17193, 4750, 2, 'Call with David Williams at Smith Education LLC. Discussed Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI. and next steps. Following up with additional materials.', NULL, '2026-02-21T23:37:44.094078', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17505, 2810, 1, 'Customer discussed the following challenges:
1. Our ''rollback'' process is manual, slow, and scary.

Proposed Synapse AIOps as a solution to address these needs. Sent proposal documentation via email.', 'email', '2026-02-22T02:57:27', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17588, 4781, 1, 'Extended call with John Davis at Smith Healthcare LLC covering their Retail infrastructure.

**Call Summary**
Great session with Smith Healthcare LLC team. They walked us through their General Business Workflow Automation requirements in detail. Clear alignment between their needs around Human error during a manual process (like patching) caused a major outage. and what Synapse AIOps delivers.

**Timeline & Urgency**
John Davis mentioned several timing factors:
- Board meeting next month where they need to present solution
- Integration with their Q2 product launch
- Team capacity available now, may not be later

Urgency is real. We should accelerate our response.

_Deal: $91988 | Stage: early | Champion: John Davis_', NULL, '2026-01-12T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17589, 4781, 1, 'Called John Davis, left callback number and availability.', NULL, '2026-01-18T19:17:00.696014', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17590, 4781, 1, 'Voicemail left to remind John Davis about required onboarding documents.', NULL, '2026-01-26T05:46:47.696349', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17591, 4781, 1, 'Productive follow-up session with Smith Healthcare LLC. Main discussion centered on Human error during a manual process (like patching) caused a major outage.. John Davis mentioned this has been a pain point for over a year. Encouraging discussion. Next steps agreed upon. Following up with technical architecture document.', NULL, '2026-02-01T23:14:25.382174', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17592, 4781, 1, 'Detailed technical discussion with Smith Healthcare LLC team. Key stakeholder: John Davis.

**Call Summary**
Extended meeting covering both business and technical aspects. John Davis brought in their architect to validate our approach to General Business Workflow Automation. Strong interest in how we solve Human error during a manual process (like patching) caused a major outage. for Retail customers.

**Key Stakeholders**
- **John Davis** (Primary Contact) - Technical Lead, strong champion, driving the evaluation
- **Chris** - CTO, technical decision maker, needs to sign off on architecture
- **Sarah** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the Head of Platform. John Davis has direct access and influence.

_Deal: $91988 | Stage: middle | Champion: John Davis_', NULL, '2026-02-07T05:39:40.295906', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17593, 4781, 1, 'Final technical validation with Smith Healthcare LLC. All concerns addressed including Human error during a manual process (like patching) caused a major outage.. John Davis pushing for approval this quarter.', NULL, '2026-02-10T02:17:00.430809', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17594, 4781, 1, 'Negotiation call with John Davis and their procurement. Working through volume discount structure for $91988 deal.', NULL, '2026-02-18T05:26:43.725192', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17595, 4781, 1, 'Extended call with John Davis at Smith Healthcare LLC covering their Retail infrastructure.

**Call Summary**
Great session with Smith Healthcare LLC team. They walked us through their General Business Workflow Automation requirements in detail. Clear alignment between their needs around Human error during a manual process (like patching) caused a major outage. and what Synapse AIOps delivers.

**Competitive Landscape**
Smith Healthcare LLC is also evaluating **Shopify** and **SAP**. Our key differentiators:
- Superior handling of Human error during a manual process (like patching) caused a major outage.
- Stronger Retail-specific features
- Better customer support reputation

John Davis mentioned they''ve had issues with Shopify''s implementation complexity in the past.

_Deal: $91988 | Stage: close | Champion: John Davis_', NULL, '2026-02-18T21:28:26.074086', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17815, 4813, 2, 'Spoke with Sarah Miller regarding their needs: Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'call', '2026-02-21T15:07:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (17908, 1168, 2, 'Client covered the following challenges:
1. We''re making decisions based on ''what happened last quarter,'' not ''what is happening right now''.

Proposed Neuron Canvas as a solution to address these needs.', 'internal', '2026-02-21T18:49:51', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (18014, 4890, 1, 'Customer covered the following challenges:
1. We can''t enforce data access policies at a granular, query-by-query level.
2. Security code reviews are slow and can''t catch every possible injection vector.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-02-21T08:00:28', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (18021, 661, 1, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs. Michael Jones requested additional information.', 'email', '2026-02-22T02:45:31', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (18036, 2841, 1, 'Client talked about the following challenges:
1. We need a 24/7 support agent, but we can''t afford to staff it with humans.
2. We need to get AI tools into the hands of the people who are closest to the client.

Proposed Neuron Canvas as a solution to address these needs.', 'internal', '2026-02-22T00:03:56', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (18079, 4924, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs. David Jones requested additional information.', 'internal', '2026-02-21T23:42:29', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (18208, 645, 1, 'Customer discussed the following challenges:
1. Our data scientists are spending all their time doing ''data cleaning'' and ''data prep''.

Proposed Prometheus AI Factory as a solution to address these needs.', 'meeting', '2026-02-21T15:11:22', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (18508, 9, 1, 'Dear Insightful Strategy Group leadership, I understand there may be some reservations regarding the implementation of advanced analytics in our process—perhaps concerns about its complexity or cost-effectiveness? Let me assure you that with proper guidance, it can significantly enhance decision making and ROI. Shall we schedule a demo to explore these benefits together? Best regards, Ava Chen', NULL, '2026-01-27T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (18519, 9, 1, 'Call Notes:
Current Challenges / Pain Points:
  - performance challenges affecting daily operations

Impact & Consequence: API response times degraded 40% in last quarter as user base grew. Lost two enterprise deals due to performance concerns in POC.

Current Solution / Competition: Using RDS PostgreSQL with default configuration. No query optimization or connection pooling. Application team unfamiliar with database tuning.

Key Questions Asked by Prospect:
  - What are common performance bottlenecks?
  - How do we identify slow queries?
  - Is there a managed solution for connection pooling?
  - What monitoring tools do you recommend?

Next Steps:
  - Set up performance audit session
  - Provide query analysis report
  - Demo connection pooling setup
  - Share performance optimization guide', 'call', '2026-01-15T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (18530, 9, 1, 'Call Notes:
Current Challenges / Pain Points:
  - performance challenges affecting daily operations

Impact & Consequence: API response times degraded 40% in last quarter as user base grew. Lost two enterprise deals due to performance concerns in POC.

Current Solution / Competition: Using RDS PostgreSQL with default configuration. No query optimization or connection pooling. Application team unfamiliar with database tuning.

Key Questions Asked by Prospect:
  - What are common performance bottlenecks?
  - How do we identify slow queries?
  - Is there a managed solution for connection pooling?
  - What monitoring tools do you recommend?

Next Steps:
  - Set up performance audit session
  - Provide query analysis report
  - Demo connection pooling setup
  - Share performance optimization guide', 'call', '2026-01-21T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (18543, 9, 1, 'I wanted to follow up on our previous discussion regarding your organization''s migration needs, specifically with regards to upgrading to our cloud-based solution. We''ve recently received a positive review from a similar client in the industry, which has further solidified our confidence in meeting your expectations for seamless transition and improved efficiency.', NULL, '2026-01-18T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (18554, 9, 1, 'I wanted to follow up on our previous discussion regarding your organization''s migration needs, specifically with regards to upgrading to our cloud-based solution. We''ve recently received a positive review from a similar client in the industry, which has further solidified our confidence in meeting your expectations for seamless transition and improved efficiency.', NULL, '2026-01-21T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (18565, 9, 1, 'I wanted to follow up on our previous discussion regarding your organization''s migration needs, specifically with regards to upgrading to our cloud-based solution. We''ve recently received a positive review from a similar client in the industry, which has further solidified our confidence in meeting your expectations for seamless transition and improved efficiency.', NULL, '2026-01-22T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (19164, 5215, 1, 'Good intro meeting with Davis Manufacturing Systems. Jane Jones outlined their Retail challenges including We want our HR team to build an ''AI Onboarding Buddy'' for new hires, but they have no technical skills.. Sending over technical overview.', NULL, '2026-02-24T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (19165, 5215, 1, 'Noted competitive positioning update and alerted sales leadership.', NULL, '2026-03-03T10:53:12.550851', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (19166, 5215, 1, 'Left VM for Jane Jones.', NULL, '2026-03-04T05:17:49.556008', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (19167, 5215, 1, 'Recorded that demo environment was provisioned.', NULL, '2026-03-12T05:58:21.297751', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (19168, 5215, 1, 'Demo went well with Davis Manufacturing Systems.', NULL, '2026-03-15T05:14:31.096309', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (19169, 5215, 1, 'Productive follow-up session with Davis Manufacturing Systems. Main discussion centered on We want our HR team to build an ''AI Onboarding Buddy'' for new hires, but they have no technical skills.. Jane Jones mentioned this has been a pain point for over a year. Encouraging discussion. Next steps agreed upon. Scheduling reference call with similar Retail customer.', NULL, '2026-03-19T02:35:56.662456', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (19170, 5215, 1, 'Proposal sent to Davis Manufacturing Systems.', NULL, '2026-03-26T22:06:13.620274', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (19171, 5215, 1, '## Meeting Notes: Davis Manufacturing Systems

Extended technical and business discussion with Jane Jones and their team at Davis Manufacturing Systems. This was a pivotal meeting in the evaluation process.

### Call Summary
Great session with Davis Manufacturing Systems team. They walked us through their Natural Language Access to Data Assets requirements in detail. Clear alignment between their needs around We want our HR team to build an ''AI Onboarding Buddy'' for new hires, but they have no technical skills. and what Neuron Canvas delivers.

### Pain Points Discussed
Jane Jones outlined the issues they''re facing with their current approach:

1. **We want our HR team to build an ''AI Onboarding Buddy'' for new hires, but they have no technical skills.** - This has been causing significant operational overhead. Jane Jones mentioned their team spends 20+ hours/week on manual workarounds.
2. **We have 20 years of customer data, but we''re not using it to generate any new insights.** - Related to the first issue. Solving one should help address the other.

Their current solution lacks the Retail-specific features they need. Been looking for alternatives for 6+ months.

### Competitive Landscape
Davis Manufacturing Systems is also evaluating **SAP** and **Shopify**. Our key differentiators:
- Superior handling of We want our HR team to build an ''AI Onboarding Buddy'' for new hires, but they have no technical skills.
- Stronger Retail-specific features
- Better customer support reputation

Jane Jones mentioned they''ve had issues with SAP''s implementation complexity in the past.

### Next Steps
1. Send final proposal with negotiated terms
2. Schedule contract review with Davis Manufacturing Systems''s legal team
3. Prepare implementation timeline and resource plan
4. Jane Jones to get final budget approval from leadership
5. Target close date: End of month

### Target Use Cases
Key use cases driving this evaluation at Davis Manufacturing Systems:

1. **Natural Language Access to Data Assets**
   - Build a chat interface that sits on top of your customer database, allowing a support agent to simply ask, "What was John Smith''s last order and shipping status?" The AI retrieves the information from multiple systems and provides a single, concise answer, dramatically improving support efficiency.
   - This is their primary driver for evaluating Neuron Canvas. Jane Jones estimates this will save their team 15+ hours per week.
   - They''ve tried addressing this with their current solution but hit scaling limitations.

2. **Unlocking Your Data**
   - Create an AI agent that can analyze sales data and provide proactive insights, such as "Your top 5 customers in the northeast region have reduced their spending this quarter." This transforms your static data into a dynamic, conversational partner that helps drive business strategy.
   - Secondary priority but equally important for their long-term roadmap.
   - Would consolidate multiple point solutions they currently maintain.

**Why This Matters:** The Natural Language Access to Data Assets use case is specifically designed to solve We want our HR team to build an ''AI Onboarding Buddy'' for new hires, but they have no technical skills. - the core issue Jane Jones raised in our first conversation.

---
**Deal Details:** $72597 ARR | **Stage:** late | **Industry:** Retail
**Champion:** Jane Jones | **Product:** Neuron Canvas', NULL, '2026-04-01T05:15:01.543881', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (19172, 5215, 1, '## Technical Deep-Dive: Davis Manufacturing Systems

Detailed walkthrough of Neuron Canvas capabilities with Davis Manufacturing Systems''s engineering and business teams. Covered architecture, integration, and roadmap.

### Call Summary
Productive discussion covering their Natural Language Access to Data Assets requirements. Jane Jones led the conversation with clear priorities around solving We want our HR team to build an ''AI Onboarding Buddy'' for new hires, but they have no technical skills.. The team was engaged and asked detailed questions about how Neuron Canvas supports Build a chat interface that sits on top of your customer database, allowing a support agent to simply ask, "What was John Smith''s last order and shipping status?" The AI retrieves the information from multiple systems and provides a single, concise answer, dramatically improving support efficiency..

### Technical Requirements
- **Primary:** We want our HR team to build an ''AI Onboarding Buddy'' for new hires, but they have no technical skills.
- **Secondary:** We have 20 years of customer data, but we''re not using it to generate any new insights.
- E-commerce platform integration
- Inventory management sync
- Integration with existing authentication systems (SSO/SAML)

### Next Steps
1. Send final proposal with negotiated terms
2. Schedule contract review with Davis Manufacturing Systems''s legal team
3. Prepare implementation timeline and resource plan
4. Jane Jones to get final budget approval from leadership

### Pain Points Discussed
Jane Jones outlined the issues they''re facing with their current approach:

1. **We want our HR team to build an ''AI Onboarding Buddy'' for new hires, but they have no technical skills.** - This has been causing significant operational overhead. Jane Jones mentioned their team spends 20+ hours/week on manual workarounds.
2. **We have 20 years of customer data, but we''re not using it to generate any new insights.** - Related to the first issue. Solving one should help address the other.

Budget has been allocated for this initiative. They need a solution in place before end of fiscal year.

### Competitive Landscape
This is a competitive deal. **Oracle** has existing relationship but Jane Jones frustrated with their roadmap. **Salesforce Commerce** in the mix but lacks Retail expertise.

Our advantages: technical depth, Retail focus, and Jane Jones as a strong champion.

---
**Deal Details:** $72597 ARR | **Stage:** late | **Industry:** Retail
**Champion:** Jane Jones | **Product:** Neuron Canvas', NULL, '2026-04-01T13:07:30.203254', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (19173, 5215, 1, 'Call with Davis Manufacturing Systems team. Main discussion centered on We want our HR team to build an ''AI Onboarding Buddy'' for new hires, but they have no technical skills.. Jane Jones mentioned this has been a pain point for over a year. Very positive signals. Davis Manufacturing Systems team aligned on moving forward. Next meeting scheduled for next week.', NULL, '2026-04-02T19:02:03.213119', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (20326, 5302, 2, 'Positive feedback from Garcia Retail Group team.', NULL, '2025-11-03T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (20327, 5302, 2, 'Discovery session with Garcia Retail Group team. Primary pain point is data management challenges. Lisa Smith to loop in their technical lead for deeper dive.', NULL, '2025-11-25T10:52:09.523004', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (20328, 5302, 2, 'Comprehensive review session with Lisa Smith regarding Synapse AIOps implementation.

**Call Summary**
Productive discussion covering their core Education requirements. Lisa Smith led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

**Competitive Landscape**
Garcia Retail Group is also evaluating **Competitor A** and **Competitor B**. Our key differentiators:
- Superior handling of scaling challenges
- Stronger Education-specific features
- Better customer support reputation

Lisa Smith mentioned they''ve had issues with Competitor A''s implementation complexity in the past.

_Deal: $32984 | Stage: early | Champion: Lisa Smith_', NULL, '2025-11-25T14:09:33.930342', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (20329, 5302, 2, 'Sent polite follow-up email with two calendar options to Lisa Smith.', NULL, '2025-12-28T00:23:16.121480', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (20330, 5302, 2, 'Waiting on finance team to approve the revised payment terms.', NULL, '2025-12-30T17:23:17.460765', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (20331, 5302, 2, 'Shared Synapse AIOps documentation.', NULL, '2026-01-23T08:56:53.606242', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (20332, 5302, 2, 'Comprehensive review session with Lisa Smith regarding Synapse AIOps implementation.

**Call Summary**
Extended meeting covering both business and technical aspects. Lisa Smith brought in their architect to validate our approach to data management challenges. Strong interest in our Education experience.

**Timeline & Urgency**
Lisa Smith mentioned several timing factors:
- Board meeting next month where they need to present solution
- Integration with their Q2 product launch
- Team capacity available now, may not be later

Urgency is real. We should accelerate our response.

**Pain Points Discussed**
Lisa Smith outlined the issues they''re facing with their current approach:


Budget has been allocated for this initiative. They need a solution in place before end of fiscal year.

_Deal: $32984 | Stage: late | Champion: Lisa Smith_', NULL, '2026-02-01T21:35:31.496874', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (20333, 5302, 2, 'Pricing discussion with Lisa Smith. Deal size around $32984. They''re comparing us to two other vendors. Decision expected in 2 weeks.', NULL, '2026-02-26T10:27:58.071964', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (20334, 5302, 2, 'Critical negotiation meeting with Garcia Retail Group. Main discussion centered on data management challenges. Lisa Smith mentioned this has been a pain point for over a year. Lisa Smith is very enthusiastic about Synapse AIOps. Strong champion potential. Preparing executive summary for their leadership.', NULL, '2026-03-13T22:56:50.873285', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (20335, 5302, 2, 'Extended call with Lisa Smith at Garcia Retail Group covering their Education infrastructure.

**Call Summary**
Deep technical conversation with Garcia Retail Group''s evaluation team. Lisa Smith has done their homework on our platform. Discussion centered on data management challenges and how we compare to their current solution.

**Pain Points Discussed**
The Garcia Retail Group team highlighted several critical challenges:


Lisa Smith emphasized that solving these issues is a top priority for their leadership team.

_Deal: $32984 | Stage: close | Champion: Lisa Smith_', NULL, '2026-03-18T15:13:35.066155', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (20336, 5302, 2, 'Sync with Lisa Smith. They''re working through data management challenges challenges. Synapse AIOps well-positioned to help.', NULL, '2026-03-30T21:05:40.172756', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22078, 5439, 1, 'Sent quote to Williams Education Solutions.', NULL, '2025-10-10T14:22:41.386880', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22079, 5439, 1, '## Technical Deep-Dive: Williams Education Solutions

Detailed walkthrough of Synapse AIOps capabilities with Williams Education Solutions''s engineering and business teams. Covered architecture, integration, and roadmap.

### Call Summary
Extended meeting covering both business and technical aspects. John Smith brought in their architect to validate our approach to data management challenges. Strong interest in our Education experience.

### Timeline & Urgency
John Smith indicated a target decision date of end of quarter. Key timeline drivers:
- Current contract with existing vendor expires in 90 days
- New fiscal year budget available starting next month
- Education priority initiative tied to this solution

**Risk:** Delay could push to next budget cycle.

### Next Steps
1. Send Synapse AIOps technical overview and architecture documentation
2. Schedule demo with John Smith''s engineering team (targeting next week)
3. Share Education case studies and reference customers
4. John Smith to gather internal requirements from their team

### Pain Points Discussed
The Williams Education Solutions team highlighted several critical challenges:


Their current solution lacks the Education-specific features they need. Been looking for alternatives for 6+ months.

---
**Deal Details:** $52143 ARR | **Stage:** early | **Industry:** Education
**Champion:** John Smith | **Product:** Synapse AIOps', NULL, '2025-10-15T06:05:08.866541', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22080, 5439, 1, 'Waiting on Williams Education Solutions decision.', NULL, '2025-11-17T18:43:27.289816', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22081, 5439, 1, 'Demo and technical discussion with John Smith''s team. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Education requirements. Budget constraints mentioned. May need to adjust proposal. Following up with technical architecture document.', NULL, '2025-12-14T10:46:20.787225', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22082, 5439, 1, 'Booked demo with Williams Education Solutions for next Tuesday.', NULL, '2026-01-28T14:46:07.036379', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22083, 5439, 1, 'Contract review meeting with Williams Education Solutions legal and John Smith. Minor redlines on SLA terms. Should close by end of month.', NULL, '2026-02-17T01:54:57.786708', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22084, 5439, 1, 'Shared troubleshooting steps via email after support raised an issue.', NULL, '2026-02-20T10:40:22.707708', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22085, 5439, 1, '## Call Summary: Williams Education Solutions

Comprehensive review session covering all aspects of their Education requirements. Multiple stakeholders present including John Smith.

### Call Summary
Productive discussion covering their core Education requirements. John Smith led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

### Competitive Landscape
Competition includes **Competitor A** (incumbent) and **Competitor B** (also evaluating). We''re differentiated on:
- Native support for their Education workflows
- More flexible pricing model
- Faster time to value

They had a bad experience with Competitor B previously - opportunity to capitalize.

### Pain Points Discussed
The Williams Education Solutions team highlighted several critical challenges:


Budget has been allocated for this initiative. They need a solution in place before end of fiscal year.

### Next Steps
1. Follow up with additional materials requested
2. Schedule next call with John Smith
3. Send meeting summary and action items

### Technical Requirements
- Enterprise-grade security
- 24/7 support availability
- Real-time data synchronization capabilities

---
**Deal Details:** $52143 ARR | **Stage:** close | **Industry:** Education
**Champion:** John Smith | **Product:** Synapse AIOps', NULL, '2026-04-06T19:26:45.424150', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22118, 5442, 1, 'Kicked off the evaluation process with Davis Finance Co. Deep dive into data management challenges and operational efficiency challenges. Their current workaround is manual and error-prone. Meeting went as expected. Following standard sales process. Next: Schedule technical demo with their engineering team.', NULL, '2025-08-07T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22119, 5442, 1, 'Moved meeting to next Thursday.', NULL, '2025-08-21T06:08:32.427880', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22120, 5442, 1, 'Detailed technical discussion with Davis Finance Co team. Key stakeholder: Emily Jones.

**Call Summary**
Productive discussion covering their core Retail requirements. Emily Jones led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

**Next Steps**
1. Prepare custom demo addressing key requirements
2. Schedule reference call with similar Retail customer
3. Send preliminary pricing and packaging options

_Deal: $51250 | Stage: middle | Champion: Emily Jones_', NULL, '2025-08-31T17:51:14.684580', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22121, 5442, 1, 'Deep-dive meeting with Davis Finance Co stakeholders. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Retail requirements. Standard evaluation process. Davis Finance Co doing due diligence. Scheduling reference call with similar Retail customer.', NULL, '2025-09-11T17:20:53.189035', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22122, 5442, 1, '## Meeting Notes: Davis Finance Co

Extended technical and business discussion with Emily Jones and their team at Davis Finance Co. This was a pivotal meeting in the evaluation process.

### Call Summary
Comprehensive call with Emily Jones and two other stakeholders from their technical team. Main focus was understanding how Neuron Canvas handles data management challenges. Good energy throughout the session.

### Pain Points Discussed
The Davis Finance Co team highlighted several critical challenges:


Their current solution lacks the Retail-specific features they need. Been looking for alternatives for 6+ months.

### Competitive Landscape
Davis Finance Co is also evaluating **Shopify** and **Salesforce Commerce**. Our key differentiators:
- Superior handling of scaling challenges
- Stronger Retail-specific features
- Better customer support reputation

Emily Jones mentioned they''ve had issues with Shopify''s implementation complexity in the past.

### Target Use Cases
The Davis Finance Co team is targeting the following deployment scenarios:


### Technical Requirements
- E-commerce platform integration
- Inventory management sync
- High availability (99.9%+ uptime requirement)

### Key Stakeholders
- **Emily Jones** (Primary Contact) - Engineering Manager, strong champion, driving the evaluation
- **Mike** - Chief Architect, technical decision maker, needs to sign off on architecture
- **Lisa** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the VP of Engineering. Emily Jones has direct access and influence.

---
**Deal Details:** $51250 ARR | **Stage:** middle | **Industry:** Retail
**Champion:** Emily Jones | **Product:** Neuron Canvas', NULL, '2025-09-27T09:02:52.366863', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22123, 5442, 1, 'Left voicemail requesting updated purchase timeline.', NULL, '2025-10-07T05:48:29.622726', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22124, 5442, 1, 'Final technical validation with Davis Finance Co. All concerns addressed including data management challenges. Emily Jones pushing for approval this quarter.', NULL, '2025-10-19T03:25:14.292006', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22125, 5442, 1, 'Extended call with Emily Jones at Davis Finance Co covering their Retail infrastructure.

**Call Summary**
Extended meeting covering both business and technical aspects. Emily Jones brought in their architect to validate our approach to data management challenges. Strong interest in our Retail experience.

**Key Stakeholders**
- **Emily Jones** (Primary Contact) - Technical Lead, strong champion, driving the evaluation
- **Jennifer** - Chief Architect, technical decision maker, needs to sign off on architecture
- **David** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the Chief Architect. Emily Jones has direct access and influence.

_Deal: $51250 | Stage: late | Champion: Emily Jones_', NULL, '2025-10-27T05:05:02.512789', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22126, 5442, 1, 'Extended call with Emily Jones at Davis Finance Co covering their Retail infrastructure.

**Call Summary**
Productive discussion covering their core Retail requirements. Emily Jones led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

**Technical Requirements**
- E-commerce platform integration
- Inventory management sync
- Real-time data synchronization capabilities

_Deal: $51250 | Stage: close | Champion: Emily Jones_', NULL, '2025-10-28T09:27:34.906661', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22494, 5501, 1, 'Client discussed the following challenges:
1. We bought a ''workflow automation'' tool, but it''s too simple and can''t handle our complex logic.

Proposed Synapse AIOps as a solution to address these needs.', 'meeting', '2026-04-06T22:57:40', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22544, 5439, 2, 'Follow-up with John Smith: Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'call', '2025-12-22T23:28:11', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22568, 1591, 1, 'Account expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-04-05T19:31:55', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22592, 5544, 2, 'Client expressed interest in OmniConnect Proxy for their data infrastructure needs. Sent proposal documentation via email.', 'call', '2026-04-06T14:39:03', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22712, 2483, 1, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'internal', '2026-03-13T21:19:41', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22729, 5616, 1, 'Customer discussed the following challenges:
1. A query ''optimizer'' bug is causing one of our most important queries to run for an hour instead of a second.
2. A query ''optimizer'' bug is causing one of our most important queries to run for an hour instead of a second.

Proposed TitanDB Enterprise as a solution to address these needs.', 'meeting', '2026-04-06T15:46:31', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22769, 5302, 2, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'meeting', '2026-03-20T23:44:46', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22771, 4094, 2, 'Account expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'email', '2026-03-21T20:20:17', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22885, 5712, 2, 'Customer talked about the following challenges:
1. We''re using a ''lambda architecture,'' and it''s way too complex to manage.
2. We need to give our users a ''single data view,'' but our data is in 20 different places.

Proposed Converge Lakehouse as a solution to address these needs.', 'email', '2026-04-06T22:55:08', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22919, 5728, 2, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs. Scheduled follow-up call for next steps.', 'internal', '2026-04-06T23:15:20', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (22979, 5763, 2, 'Customer covered the following challenges:
1. We don''t have the time or expertise to monitor security forums and apply patches ourselves.

Proposed TitanDB Enterprise as a solution to address these needs.', 'email', '2026-04-06T07:26:41', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23026, 5790, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'call', '2026-04-06T19:25:36', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23040, 5798, 2, 'Customer reviewed the following challenges:
1. Our data is in a proprietary format, and our AI libraries can''t read it.
2. We have no way to ''mask'' sensitive data (like credit card numbers) for our analysts.

Proposed Converge Lakehouse as a solution to address these needs.', 'internal', '2026-04-06T21:27:39', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23047, 3580, 2, 'Call with Michael Miller at Brown Technology LLC: Client discussed the following challenges:
1. Our developers are spending 30% of their time just writing boilerplate SQL and CREATE scripts.
2. I have 5,000 alerts in my inbox, and 99% of them are just ''CPU > 80% for 5 mins''. It''s just noise.

Proposed CodeCraft DevKit as a solution to address these needs.', 'meeting', '2026-03-11T20:53:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23094, 5829, 1, 'Account discussed the following challenges:
1. Our ''AI'' app is a ''black box.'' We have no idea why it made a specific decision.

Proposed Prometheus AI Factory as a solution to address these needs.', 'internal', '2026-04-06T23:12:33', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23108, 4072, 1, 'Customer reviewed the following challenges:
1. We need to re-shard our data, but it will require months of application downtime and code changes.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-03-29T14:51:50', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23113, 4890, 2, 'Client reviewed the following challenges:
1. Our ''hot'' shards are constantly overloaded, while other shards are idle.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-02-26T07:45:58', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23198, 5874, 2, 'Customer discussed the following challenges:
1. It''s impossible to differentiate between application-level users and their database activity.

Proposed Neuron Canvas as a solution to address these needs.', 'email', '2026-04-06T23:16:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23217, 625, 2, 'Account talked about the following challenges:
1. Our investors are asking about our business continuity plan, and ''community support'' isn''t a good answer.
2. We keep ''rediscovering'' solutions to problems our team has already solved.

Proposed OS Guardian Support as a solution to address these needs.', 'email', '2026-03-05T07:01:36', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23293, 5916, 1, 'Meeting notes for Williams Healthcare Corp: Customer discussed the following challenges:
1. Our team is skilled in other databases, but not this one, and we''re making ''rookie'' mistakes.

Proposed OS Guardian Support as a solution to address these needs.', 'meeting', '2026-04-06T21:17:31', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23432, 3075, 2, 'Customer reviewed the following challenges:
1. When we hire a new employee, it takes IT, HR, and Finance 3 days to get all their accounts set up.
2. Our runbooks are always out of date. We want an AI that can learn how to fix a problem.

Proposed Synapse AIOps as a solution to address these needs.', 'call', '2026-03-18T17:40:51', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23443, 2887, 1, 'Customer discussed the following challenges:
1. Our IT team is answering the same 20 questions every single day.
2. I want to just ask my data a question: ''How many units did we sell in Boston last month?''

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-03-10T13:02:32', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23470, 3140, 1, 'Discussion with Jones Healthcare Solutions team: Client reviewed the following challenges:
1. Our development frameworks don''t integrate well with the open-source database.

Proposed PillarDB Standard as a solution to address these needs.', 'call', '2026-03-24T07:57:53', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23509, 6011, 1, 'Meeting notes for Johnson Healthcare Group: Account expressed interest in Neuron Canvas for their data infrastructure needs.', 'internal', '2026-04-06T22:31:55', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23515, 3951, 1, 'Account went over the following challenges:
1. We need to ''roll back'' our AI model to a previous version, but we can''t.
2. Our data scientists are running ''Jupyter notebooks'' on their laptops with production data, which is a massive security breach.

Proposed Prometheus AI Factory as a solution to address these needs.', 'email', '2026-04-01T17:53:14', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23537, 3580, 2, 'Customer discussed the following challenges:
1. We have no way to compare the schema in ''dev'' vs. ''prod'' to see what''s different.
2. Our data quality is poor because we have no automated way to test and validate data as it moves.

Proposed CodeCraft DevKit as a solution to address these needs.', 'meeting', '2026-04-01T05:45:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23630, 3824, 1, 'Call with Jane Davis at Jones Healthcare Solutions: Account discussed the following challenges:
1. We need a DBA to ''approve'' all queries, but this is a huge bottleneck for our developers.
2. Our troubleshooting process is ''ad-hoc'' and relies on one or two ''heroes'' who know everything.

Proposed ClarityDB Guardian as a solution to address these needs.', 'email', '2026-02-26T16:31:06', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23668, 6085, 2, 'Customer discussed the following challenges:
1. We need a 24/7 support agent, but we can''t afford to staff it with humans.

Proposed Neuron Canvas as a solution to address these needs. Action items documented and assigned.', 'meeting', '2026-04-06T21:10:34', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23676, 5798, 1, 'Customer covered the following challenges:
1. Our automation tools are all ''IT-focused.'' They can''t talk to our business apps like Workday or SAP.

Proposed Converge Lakehouse as a solution to address these needs.', 'email', '2026-04-06T16:53:01', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23732, 6112, 1, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'call', '2026-04-06T22:33:05', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23753, 2282, 2, 'Prospect discussed the following challenges:
1. Database maintenance (patching, upgrades) requires a full application outage.
2. We can''t scale writes horizontally, creating a massive bottleneck for our fast-growing application.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-03-27T00:10:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23870, 5215, 2, 'Customer discussed the following challenges:
1. Our team knows the business problem, but they don''t know Python or AI.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-03-28T11:16:12', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (23872, 6166, 1, 'Customer discussed the following challenges:
1. Our ''automation'' is just a collection of 500 different bash and PowerShell scripts that only one person understands.

Proposed Synapse AIOps as a solution to address these needs.', 'call', '2026-04-06T23:29:26', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24001, 6237, 2, 'Customer reviewed the following challenges:
1. We have many microservices, and the combined connection count is crashing the database.
2. Our load balancer isn''t database-aware, so it keeps sending traffic to a node that is overloaded or in maintenance.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-04-06T15:11:43', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24031, 4556, 2, 'Client discussed the following challenges:
1. Our analysts only know SQL, but they need to query data from a MongoDB or a Kafka stream.
2. We have ''data silos''—our BI team uses the warehouse, and our AI team uses the lake, and they''re looking at different data.

Proposed Converge Lakehouse as a solution to address these needs.', 'meeting', '2026-03-30T09:45:06', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24043, 6257, 1, 'Customer discussed the following challenges:
1. We can''t ingest and query our IoT sensor data fast enough.
2. Only 5% of our company (the ''data team'') can actually access and analyze our data. It''s a bottleneck.

Proposed Converge Lakehouse as a solution to address these needs.', 'email', '2026-04-06T14:54:46', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24056, 6265, 2, 'Customer talked about the following challenges:
1. Due to performance degradation linked with local database monitoring activities, we must disable these features for now.

Proposed PillarDB Standard as a solution to address these needs.', 'call', '2026-04-06T23:59:29', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24057, 6266, 1, 'Account expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'meeting', '2026-04-06T22:54:46', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24176, 6323, 1, 'Customer discussed the following challenges:
1. Our application''s user experience is poor due to high database latency.
2. Our database is ''write-bound''; we are bottlenecked on a single server''s write capacity.

Proposed TitanDB Enterprise as a solution to address these needs.', 'meeting', '2026-04-06T13:58:03', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24296, 625, 1, 'Customer discussed the following challenges:
1. We love open-source, but our CTO is worried about running our business on unsupported software.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-03-27T17:17:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24303, 6381, 1, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs. Sent proposal documentation via email.', 'call', '2026-04-06T19:13:27', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24324, 6391, 2, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'call', '2026-04-06T16:08:04', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24399, 6427, 2, 'Customer covered the following challenges:
1. We can''t afford 24/7/365 enterprise support for every database.
2. A bug is causing data inconsistencies, which is a huge problem for our reporting.

Proposed PillarDB Standard as a solution to address these needs.', 'call', '2026-04-06T22:30:41', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24447, 6443, 1, 'Client talked about the following challenges:
1. We don''t have the time or expertise to monitor security forums and apply patches ourselves.

Proposed PillarDB Standard as a solution to address these needs. Action items documented and assigned.', 'email', '2026-04-06T11:29:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24503, 6468, 1, 'Customer discussed the following challenges:
1. We can''t prove to our auditors that data is encrypted everywhere.

Proposed TitanDB Enterprise as a solution to address these needs. Sent proposal documentation via email.', 'meeting', '2026-04-06T18:47:51', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24568, 6499, 1, 'Customer covered the following challenges:
1. We just need someone to call during business hours if our internal reporting database fails.
2. Our CI/CD pipeline depends on a database that is completely unsupported.

Proposed PillarDB Standard as a solution to address these needs. Sent proposal documentation via email.', 'meeting', '2026-04-06T23:14:21', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24618, 4169, 1, 'Customer discussed the following challenges:
1. We can''t find clear documentation on advanced features like replication or partitioning.

Proposed OS Guardian Support as a solution to address these needs. Will follow up with Jane Johnson next week.', 'internal', '2026-04-03T10:21:19', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24630, 6531, 2, 'Account discussed the following challenges:
1. Our team is wasting time on blogs and forums, finding conflicting and outdated advice.
2. Our team is wasting time on blogs and forums, finding conflicting and outdated advice.

Proposed OS Guardian Support as a solution to address these needs.', 'internal', '2026-04-06T22:40:32', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24684, 6560, 2, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-04-06T12:28:35', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24686, 3587, 1, 'Account covered the following challenges:
1. Our team is skilled in other databases, but not this one, and we''re making ''rookie'' mistakes.
2. The public documentation is good for ''hello world,'' but not for our complex production problem.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-04-03T06:51:35', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24699, 6565, 1, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'email', '2026-04-06T21:55:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24743, 6583, 1, 'Customer reviewed the following challenges:
1. Our data quality is poor, so our AI model''s accuracy is poor. ''Garbage in, garbage out''.

Proposed Prometheus AI Factory as a solution to address these needs. Will follow up with Emily Williams next week.', 'email', '2026-04-06T19:52:33', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24752, 6589, 1, 'Call with Lisa Williams at Williams Technology Co: Customer went over the following challenges:
1. We have PII data in an S3 bucket, and we can''t control who accesses it.

Proposed Converge Lakehouse as a solution to address these needs.', 'email', '2026-04-06T22:56:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24773, 6600, 1, 'Account expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'meeting', '2026-04-06T12:48:47', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24829, 6622, 2, 'Call with Lisa Williams at Davis Retail Inc: Client discussed the following challenges:
1. We need an automated ''go/no-go'' decision for our CI/CD pipeline based on real-time performance.

Proposed Synapse AIOps as a solution to address these needs.', 'internal', '2026-04-06T22:26:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24837, 6626, 2, 'Customer discussed the following challenges:
1. We have no historical data. We can''t see what ''normal'' performance looked like last Tuesday.

Proposed ClarityDB Guardian as a solution to address these needs.', 'call', '2026-04-06T23:17:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24879, 6643, 1, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'call', '2026-04-06T19:25:20', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (24881, 5616, 2, 'Customer discussed the following challenges:
1. We are about to launch our most important new service, and we''re not confident the database can handle it.
2. Encrypting our large database would require an unacceptable amount of downtime.

Proposed TitanDB Enterprise as a solution to address these needs.', 'call', '2026-04-06T15:31:31', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25018, 2956, 1, 'Customer discussed the following challenges:
1. Our native database auditing is too performance-intensive, so we have to leave it off.
2. The database is spending more CPU on connection setup/teardown than on running queries.

Proposed OmniConnect Proxy as a solution to address these needs. Lisa Miller requested additional information.', 'call', '2026-03-31T16:24:54', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25037, 6693, 1, 'Client discussed the following challenges:
1. I''m on my phone, and I can''t type a complex, 100-character command to fix a problem.

Proposed Synapse AIOps as a solution to address these needs. Sent proposal documentation via email.', 'internal', '2026-04-10T23:53:34', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25060, 2662, 2, 'Customer went over the following challenges:
1. We need to ''mask'' our production data (to remove PII) before we can put it in a test environment.

Proposed ClarityDB Guardian as a solution to address these needs.', 'internal', '2026-03-16T14:11:30', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25092, 6166, 1, 'Call with Sarah Smith at Brown Healthcare Solutions: Customer discussed the following challenges:
1. Our ''release process'' is one person staring at 10 different dashboards for 30 minutes after a deploy.

Proposed Synapse AIOps as a solution to address these needs.', 'call', '2026-04-08T00:11:54', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25114, 1591, 2, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'call', '2026-04-05T17:40:31', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25125, 6643, 1, 'Account expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'call', '2026-04-10T21:11:17', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25183, 5439, 1, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'email', '2026-01-28T01:27:53', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25286, 6813, 2, 'Discussion with Johnson Healthcare Ltd team: Customer discussed the following challenges:
1. Our team''s skills are getting stale, and they aren''t up-to-date on the latest features.
2. Our IT policy mandates that all production systems must have a support contract.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-04-10T13:06:52', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25328, 6257, 1, 'Prospect covered the following challenges:
1. Our data warehouse is too expensive, and we''re paying a fortune for storage and compute.

Proposed Converge Lakehouse as a solution to address these needs. Emily Garcia requested additional information.', 'meeting', '2026-04-09T19:16:57', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25394, 6871, 1, 'Discussion with Miller Finance LLC team: Client reviewed the following challenges:
1. We need to ''vectorize'' our 10 million documents, but we don''t have the pipeline or ''know-how'' to do it.

Proposed Prometheus AI Factory as a solution to address these needs.', 'internal', '2026-04-10T15:03:17', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25397, 5829, 1, 'Customer discussed the following challenges:
1. Our developers see AI as a ''threat,'' not a ''tool'' that can help them.

Proposed Prometheus AI Factory as a solution to address these needs.', 'email', '2026-04-10T15:54:44', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25438, 6889, 2, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'call', '2026-04-10T16:55:09', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25446, 6622, 1, 'Customer discussed the following challenges:
1. By the time we''ve triaged the alerts and escalated to the right team, the incident has been going for 30 minutes.

Proposed Synapse AIOps as a solution to address these needs.', 'email', '2026-04-10T19:45:20', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25455, 6898, 1, 'Customer covered the following challenges:
1. The database is spending more CPU on connection setup/teardown than on running queries.
2. Our developers are not all security experts, and we can''t be sure all inputs are properly sanitized.

Proposed OmniConnect Proxy as a solution to address these needs.', 'meeting', '2026-04-10T12:51:54', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25478, 2483, 1, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs. Scheduled follow-up call for next steps.', 'meeting', '2026-02-24T14:47:47', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25552, 4483, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'email', '2026-01-07T12:49:59', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25660, 6565, 2, 'Prospect reviewed the following challenges:
1. We need to ''roll back'' our AI model to a previous version, but we can''t.

Proposed Prometheus AI Factory as a solution to address these needs.', 'meeting', '2026-04-09T18:00:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25694, 4242, 2, 'Session notes for Davis Retail Group: Customer discussed the following challenges:
1. Our ''federated query'' tool is too slow and can''t handle complex joins.

Proposed Converge Lakehouse as a solution to address these needs.', 'internal', '2026-03-11T02:46:39', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25838, 7087, 2, 'Customer discussed the following challenges:
1. Our database has 500 tables, and no one understands how they all relate.

Proposed CodeCraft DevKit as a solution to address these needs.', 'internal', '2026-04-10T14:49:57', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25960, 7155, 1, 'Customer discussed the following challenges:
1. Provisioning a new database replica is a complex, 20-step manual process.

Proposed TitanDB Enterprise as a solution to address these needs.', 'internal', '2026-04-10T10:14:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25968, 7160, 1, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs. Scheduled follow-up call for next steps.', 'call', '2026-04-10T19:08:16', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (25994, 2887, 2, 'Customer discussed the following challenges:
1. Our team knows the business problem, but they don''t know Python or AI.

Proposed Neuron Canvas as a solution to address these needs.', 'internal', '2026-03-23T08:49:40', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26053, 7207, 1, 'Customer discussed the following challenges:
1. Our data is ''raw''; it''s not ''labeled'' or ''curated'' for AI.
2. We want to use a powerful LLM, but it needs to be ''grounded'' in our company''s specific data.

Proposed Prometheus AI Factory as a solution to address these needs.', 'email', '2026-04-10T17:45:14', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26215, 4731, 2, 'Customer discussed the following challenges:
1. We have no version control for our data pipelines; if one breaks, it''s a nightmare to fix.
2. It''s impossible to see the ''big picture'' of our data.

Proposed CodeCraft DevKit as a solution to address these needs. Action items documented and assigned.', 'internal', '2026-02-09T11:47:33', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26329, 4072, 1, 'Customer discussed the following challenges:
1. We have to ''pre-define'' our schema, but our data is evolving too quickly.

Proposed TitanDB Enterprise as a solution to address these needs.', 'call', '2026-02-24T03:50:08', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26356, 7359, 2, 'Account expressed interest in Synapse AIOps for their data infrastructure needs.', 'call', '2026-04-10T17:43:42', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26367, 6427, 2, 'Customer discussed the following challenges:
1. We need a support contract to be compliant with our internal IT policies, but the enterprise one is too expensive.
2. Our team is spending time trying to find workarounds for bugs instead of building features.

Proposed PillarDB Standard as a solution to address these needs. Action items documented and assigned.', 'meeting', '2026-04-07T06:14:01', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26479, 7420, 1, 'Customer talked about the following challenges:
1. Our load balancer isn''t database-aware, so it keeps sending traffic to a node that is overloaded or in maintenance.

Proposed OmniConnect Proxy as a solution to address these needs.', 'email', '2026-04-10T18:14:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26492, 7425, 1, 'Customer talked about the following challenges:
1. Our AI team is in a ''silo.'' They''re building models, but the business doesn''t understand them or use them.
2. We want to ''prototype'' an AI idea quickly, but it takes weeks to get a ''hello world'' app running.

Proposed Neuron Canvas as a solution to address these needs.', 'call', '2026-04-10T21:10:47', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26510, 6085, 1, 'Prospect discussed the following challenges:
1. Our ''Finance'' team knows exactly what they want, but they can''t explain it to our AI engineers.
2. We want to build a ''chatbot'' for our prospects, but we don''t want it to ''make up'' answers.

Proposed Neuron Canvas as a solution to address these needs.', 'internal', '2026-04-09T00:30:52', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26530, 6266, 1, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'meeting', '2026-04-09T03:52:29', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26558, 7459, 1, 'Customer covered the following challenges:
1. We can''t scale writes horizontally, creating a massive bottleneck for our fast-growing application.
2. We have many microservices, and the combined connection count is crashing the database.

Proposed OmniConnect Proxy as a solution to address these needs.', 'email', '2026-04-10T11:41:17', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26626, 4094, 1, 'Prospect expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'call', '2026-02-25T05:20:07', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26675, 7521, 2, 'Customer discussed the following challenges:
1. We are hitting the maximum RAM and CPU of our biggest available server, and we have nowhere else to ''scale up''.

Proposed TitanDB Enterprise as a solution to address these needs.', 'meeting', '2026-04-10T19:09:14', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26711, 7542, 1, 'Follow-up with Michael Miller: Customer talked about the following challenges:
1. We can''t justify the high cost of an enterprise license for our dev/test environments.
2. Our intranet portal went down, and our engineers spent two days on forums trying to fix it.

Proposed PillarDB Standard as a solution to address these needs.', 'meeting', '2026-04-10T09:05:17', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26757, 7568, 2, 'Prospect expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'call', '2026-04-10T22:48:26', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26866, 7632, 1, 'Follow-up with Michael Johnson: Account expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'call', '2026-04-10T19:40:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26900, 7645, 2, 'Client expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-04-10T22:00:16', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26924, 7542, 1, 'Follow-up with Michael Miller: Customer covered the following challenges:
1. Our team is spending time trying to find workarounds for bugs instead of building features.
2. Our analytics dashboards for our Tier 2 apps are taking too long to load.

Proposed PillarDB Standard as a solution to address these needs.', 'call', '2026-04-10T20:04:33', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26935, 7657, 2, 'Customer talked about the following challenges:
1. We have no centralized log of all database activity across our entire fleet.
2. Our native database auditing is too performance-intensive, so we have to leave it off.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-04-10T22:52:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (26998, 3332, 1, 'Discussion with Garcia Finance Group team: Client expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'call', '2026-03-29T13:19:46', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27028, 7707, 1, 'Client discussed the following challenges:
1. Our current tools can''t draw diagrams for our specific database dialect.
2. Our data quality is poor because we have no automated way to test and validate data as it moves.

Proposed CodeCraft DevKit as a solution to address these needs.', 'email', '2026-04-10T20:07:58', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27100, 7733, 1, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'call', '2026-04-10T23:38:31', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27164, 6237, 2, 'Client discussed the following challenges:
1. Database maintenance (patching, upgrades) requires a full application outage.

Proposed OmniConnect Proxy as a solution to address these needs.', 'email', '2026-04-09T01:34:59', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27285, 7806, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'meeting', '2026-04-10T10:09:03', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27339, 4242, 2, 'Customer covered the following challenges:
1. Our data warehouse can''t handle our semi-structured (JSON, Avro) data.
2. We just bought a new tool, and now we have to build a new pipeline to get data into it.

Proposed Converge Lakehouse as a solution to address these needs.', 'internal', '2026-02-24T04:53:06', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27353, 7835, 2, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs. Will follow up with John Davis next week.', 'internal', '2026-04-10T09:22:19', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27396, 6085, 2, 'Customer discussed the following challenges:
1. We want to embed ''analytics'' into our app, but we need it to be ''conversational''.

Proposed Neuron Canvas as a solution to address these needs. Will follow up with Robert Davis next week.', 'meeting', '2026-04-08T09:12:32', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27410, 7207, 1, 'Call with David Brown at Jones Healthcare Inc: Customer discussed the following challenges:
1. Building the ''platform'' (Kubernetes, networking, security) is taking 90% of our time, and building the ''AI'' is taking 10%.
2. We want to use generative AI, but our company policy forbids sending any customer data to a public, third-party API.

Proposed Prometheus AI Factory as a solution to address these needs.', 'internal', '2026-04-10T17:36:36', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27487, 4111, 1, 'Customer reviewed the following challenges:
1. We can''t get ''real-time'' data into our warehouse; our BI reports are always a day old.

Proposed Converge Lakehouse as a solution to address these needs.', 'call', '2026-03-05T11:52:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27491, 4303, 1, 'Customer discussed the following challenges:
1. We''re launching a new marketing campaign, and we have no idea if the database can handle the 5x traffic increase.

Proposed ClarityDB Guardian as a solution to address these needs.', 'call', '2026-03-19T16:24:35', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27506, 7894, 2, 'Customer discussed the following challenges:
1. Connection storms during a restart or deployment regularly cause site-wide outages.
2. We need to provide PCI-DSS/HIPAA/SOX compliance reports, but our database logs are insufficient.

Proposed OmniConnect Proxy as a solution to address these needs.', 'email', '2026-04-10T23:09:51', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27657, 7963, 2, 'Customer reviewed the following challenges:
1. We''re great at solving the same problem over and over, but we''re terrible at solving new problems.

Proposed Synapse AIOps as a solution to address these needs.', 'call', '2026-04-10T18:10:34', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27690, 7984, 2, 'Customer talked about the following challenges:
1. We need to add read replicas, but the replication in the open-source version is unreliable.

Proposed TitanDB Enterprise as a solution to address these needs. Johnson Manufacturing Ltd team seems very excited.', 'email', '2026-04-10T17:14:10', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27726, 6583, 1, 'Prospect discussed the following challenges:
1. Our ''database documentation'' is an ERD diagram in Visio that''s 5 years out of date.
2. We have 100 ''AI experiments'' but 0 ''AI products'' in production.

Proposed Prometheus AI Factory as a solution to address these needs.', 'call', '2026-04-06T21:58:13', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27732, 3140, 2, 'Meeting notes for Jones Healthcare Solutions: Client went over the following challenges:
1. Our database is ''end-of-life'' by the community, but we can''t upgrade it yet, so we are exposed.
2. We have 100+ important, but not ''mission-critical,'' apps that have no support.

Proposed PillarDB Standard as a solution to address these needs.', 'internal', '2026-03-05T17:14:08', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27776, 8019, 2, 'Prospect discussed the following challenges:
1. We have ''alert fatigue.'' Our engineers are ignoring P1 alerts because 90% of them are false positives.

Proposed Synapse AIOps as a solution to address these needs.', 'internal', '2026-04-10T23:48:05', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27795, 8025, 1, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'meeting', '2026-04-10T21:34:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27890, 8073, 1, 'Customer discussed the following challenges:
1. We want to empower our ''power users'' in Excel to build AI models.

Proposed Neuron Canvas as a solution to address these needs.', 'email', '2026-04-10T12:24:09', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27902, 625, 1, 'Client discussed the following challenges:
1. Our new hires are struggling because there''s no central, reliable source of information.
2. We need our engineers to be more self-sufficient and less reliant on a few ''gurus'' on the team.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-03-22T16:56:02', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27937, 6600, 2, 'Call with Lisa Garcia at Williams Retail Co: Prospect expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'internal', '2026-04-09T05:52:43', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27940, 3353, 1, 'Call with Emily Johnson at Smith Education Group: Customer discussed the following challenges:
1. We have an alert. Our runbook has 20 ''if-then'' steps to diagnose it. Why can''t a bot just do that for us?

Proposed ClarityDB Guardian as a solution to address these needs.', 'call', '2026-03-22T04:51:49', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27955, 6499, 1, 'Follow-up with Lisa Miller: Customer discussed the following challenges:
1. We don''t want to be on the ''bleeding edge''; we want a stable, patched version.

Proposed PillarDB Standard as a solution to address these needs.', 'internal', '2026-04-09T10:48:37', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27973, 8106, 2, 'Prospect expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'email', '2026-04-10T17:41:57', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (27992, 8118, 2, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-04-10T19:06:21', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28022, 8130, 2, 'Account reviewed the following challenges:
1. We want to know if this new index will actually improve performance, not just guess.

Proposed CodeCraft DevKit as a solution to address these needs.', 'internal', '2026-04-10T22:55:42', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28026, 8132, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'email', '2026-04-10T20:48:17', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28032, 8136, 2, 'Prospect expressed interest in Synapse AIOps for their data infrastructure needs.', 'internal', '2026-04-10T23:59:44', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28081, 5616, 2, 'Customer discussed the following challenges:
1. We are experiencing frequent locking and contention issues that block transactions.

Proposed TitanDB Enterprise as a solution to address these needs.', 'email', '2026-04-10T23:02:51', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28291, 4094, 1, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'internal', '2026-04-09T18:21:50', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28311, 2581, 1, 'Call with Sarah Johnson at Smith Healthcare Group: Customer discussed the following challenges:
1. We get alerts at 3 AM for issues that could have waited until morning.

Proposed ClarityDB Guardian as a solution to address these needs.', 'email', '2026-03-06T22:35:25', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28374, 8298, 2, 'Account talked about the following challenges:
1. We have 10 tables for ''accounts'' with different naming conventions (e.g., cust, account, acct_account).
2. A developer made a ''small change'' to a table that broke three other services.

Proposed CodeCraft DevKit as a solution to address these needs.', 'email', '2026-04-10T15:29:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28394, 7835, 2, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'internal', '2026-04-10T09:14:49', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28411, 3587, 2, 'Customer talked about the following challenges:
1. We need our team to get certified to prove their skills and build our internal expertise.

Proposed OS Guardian Support as a solution to address these needs.', 'meeting', '2026-04-08T05:22:15', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28432, 8322, 2, 'Client discussed the following challenges:
1. We want our AI to cite its sources. ''I got this answer from the ''Employee Handbook, page 52''.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-04-10T16:37:39', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28553, 6583, 2, 'Customer discussed the following challenges:
1. Our infrastructure does not support enforcing precise access rules on a per-query basis at this time.

Proposed Prometheus AI Factory as a solution to address these needs.', 'email', '2026-04-10T17:20:06', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28648, 4111, 1, 'Customer covered the following challenges:
1. We can''t query our ''data in place''; we have to move everything to one central location first.
2. We spend months building complex data pipelines just to join two tables from two different systems.

Proposed Converge Lakehouse as a solution to address these needs. Michael Smith requested additional information.', 'call', '2026-03-19T04:33:09', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28655, 8431, 2, 'Customer talked about the following challenges:
1. We need to trace a single user''s session from when they log in to when they log out.

Proposed ClarityDB Guardian as a solution to address these needs.', 'internal', '2026-04-10T23:55:06', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28796, 8501, 2, 'Customer discussed the following challenges:
1. Our compliance audits are manual, time-consuming, and prone to errors.

Proposed OmniConnect Proxy as a solution to address these needs.', 'email', '2026-04-10T19:51:34', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28797, 8502, 1, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'meeting', '2026-04-10T15:37:34', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28923, 6583, 2, 'Client discussed the following challenges:
1. We need ''predictable'' costs. The ''pay-as-you-go'' public APIs are too volatile for our budget.
2. We can''t ''scale'' our AI. We''re stuck in ''proof-of-concept'' hell.

Proposed Prometheus AI Factory as a solution to address these needs.', 'call', '2026-04-07T09:37:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28957, 6443, 2, 'Customer discussed the following challenges:
1. We need better caching and memory management than the community version offers.

Proposed PillarDB Standard as a solution to address these needs.', 'meeting', '2026-04-09T06:39:55', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (28999, 8605, 1, 'Customer discussed the following challenges:
1. We want to offer ''real-time personalization'' on our e-commerce site, but our data is too stale.

Proposed Converge Lakehouse as a solution to address these needs.', 'call', '2026-04-10T21:22:21', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29043, 8628, 2, 'Customer talked about the following challenges:
1. We are spending way too much on database hardware because we just ''buy the biggest box'' to be safe.
2. Our developers ''tested'' their code, but it still caused a P1 incident in platformion.

Proposed ClarityDB Guardian as a solution to address these needs.', 'call', '2026-04-10T15:22:53', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29076, 8643, 2, 'Customer reviewed the following challenges:
1. We can''t see the ''blast radius'' of a failed component. Does this one server impact one customer or all customers?
2. Our automation can run a fix, but it can''t decide on the fix. It can''t reason.

Proposed Synapse AIOps as a solution to address these needs.', 'internal', '2026-04-10T22:56:01', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29081, 3806, 1, 'Meeting notes for Brown Technology Ltd: Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'email', '2026-03-16T04:55:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29088, 1769, 2, 'Meeting notes for Davis Healthcare Group: Client discussed the following challenges:
1. Our runbooks are in Confluence, and no one reads them. We want a ''bot'' to be the runbook.

Proposed Neuron Canvas as a solution to address these needs.', 'internal', '2026-04-05T00:51:37', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29108, 1769, 2, 'Client covered the following challenges:
1. We''re making decisions based on ''what happened last quarter,'' not ''what is happening right now''.
2. We don''t want AI to be a ''scary'' thing; we want it to be an ''enabling'' thing for all our employees.

Proposed Neuron Canvas as a solution to address these needs.', 'email', '2026-04-04T15:11:29', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29206, 8702, 1, 'Follow-up with Robert Brown: Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'meeting', '2026-04-10T20:07:02', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29213, 8705, 2, 'Account discussed the following challenges:
1. We have to over-provision our database hardware just to handle the connection load, which is expensive.
2. We have no way to detect or block ''blind'' SQL injection attacks that happen slowly over time.

Proposed OmniConnect Proxy as a solution to address these needs. Sent proposal documentation via email.', 'email', '2026-04-10T13:58:21', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29214, 4242, 2, 'Call with Emily Davis at Davis Retail Group: Customer discussed the following challenges:
1. Our warehouse and our lake are constantly out of sync, leading to conflicting reports.
2. We have ''data silos''—our BI team uses the warehouse, and our AI team uses the lake, and they''re looking at different data.

Proposed Converge Lakehouse as a solution to address these needs.', 'internal', '2026-02-22T23:17:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29234, 6600, 1, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'call', '2026-04-08T16:10:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29285, 8739, 2, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs. Will follow up with Emily Smith next week.', 'email', '2026-04-10T15:41:59', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29344, 6531, 2, 'Customer reviewed the following challenges:
1. We need our team to get certified to prove their skills and build our internal expertise.
2. We keep ''rediscovering'' solutions to problems our team has already solved.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-04-06T21:30:20', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29418, 8802, 1, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'internal', '2026-04-10T21:38:25', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29478, 4072, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'email', '2026-03-03T16:00:09', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29503, 5790, 2, 'Prospect went over the following challenges:
1. We spend months building complex data pipelines just to join two tables from two different systems.

Proposed Converge Lakehouse as a solution to address these needs.', 'email', '2026-04-10T15:19:54', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29558, 6600, 1, 'Prospect expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'meeting', '2026-04-09T16:07:31', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29658, 8905, 2, 'Client expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'internal', '2026-04-10T17:37:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29735, 8938, 1, 'Customer covered the following challenges:
1. We want to include ''database health'' as a ''go/no-go'' gate in our Jenkins/GitLab pipeline, but we can''t.
2. We can''t see the database-level ''coverage'' of our QA tests.

Proposed ClarityDB Guardian as a solution to address these needs.', 'internal', '2026-04-10T17:16:25', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29859, 8995, 1, 'Prospect discussed the following challenges:
1. Our business users don''t know SQL, so they can''t ''talk'' to our database.
2. Our data is in 10 different systems, and we can''t get a ''single view'' of it.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-04-10T23:29:15', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29868, 2476, 1, 'Account talked about the following challenges:
1. A lost backup tape or stolen laptop could lead to a massive, reportable data breach.
2. A lost backup tape or stolen laptop could lead to a massive, reportable data breach.

Proposed TitanDB Enterprise as a solution to address these needs.', 'internal', '2026-03-28T16:41:30', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (29910, 2887, 2, 'Customer went over the following challenges:
1. Our Web Application Firewall (WAF) is too generic and misses sophisticated, database-specific attacks.

Proposed Neuron Canvas as a solution to address these needs.', 'internal', '2026-04-10T08:26:33', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30041, 2581, 2, 'Customer reviewed the following challenges:
1. We have a ''phishing'' alert. Our analyst now has to manually check 5 different tools (AD, email log, firewall log) to see what happened.
2. This query is fast 99% of the time, but slow 1% of the time. We need to know why.

Proposed ClarityDB Guardian as a solution to address these needs.', 'email', '2026-04-08T13:25:50', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30045, 9092, 1, 'Customer discussed the following challenges:
1. Our CEO just announced an ''AI initiative,'' but our infrastructure isn''t ready.
2. We''re afraid of ''vendor lock-in'' with a single public AI provider.

Proposed Prometheus AI Factory as a solution to address these needs.', 'email', '2026-04-10T19:39:06', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30132, 9138, 2, 'Customer discussed the following challenges:
1. Our team needs to move faster, but they are slowed down by searching for answers.
2. Our new hires are struggling because there''s no central, reliable source of information.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-04-10T23:32:53', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30148, 9145, 2, 'Customer discussed the following challenges:
1. Our IT team is answering the same 20 questions every single day.
2. Our data is in 10 different systems, and we can''t get a ''single view'' of it.

Proposed Neuron Canvas as a solution to address these needs.', 'email', '2026-04-10T14:09:24', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30214, 9174, 1, 'Customer discussed the following challenges:
1. We need a visual, low-code environment for our data analysts to build their own pipelines.
2. We have no way to compare the schema in ''dev'' vs. ''prod'' to see what''s different.

Proposed CodeCraft DevKit as a solution to address these needs. Action items documented and assigned.', 'meeting', '2026-04-10T23:32:07', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30247, 9190, 2, 'Customer discussed the following challenges:
1. Our developers are complaining that their test environments are too slow, which slows down development.
2. We need a vendor to help us with upgrade planning and best practices.

Proposed PillarDB Standard as a solution to address these needs.', 'email', '2026-04-10T23:00:35', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30265, 9200, 1, 'Customer discussed the following challenges:
1. We can''t get a root cause analysis (RCA) for outages, so we can''t prevent them from recurring.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-04-10T11:31:42', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30278, 6265, 2, 'Customer discussed the following challenges:
1. We want access to the official documentation and knowledge base, not just blog posts.
2. We can''t justify the high cost of an enterprise license for our dev/test environments.

Proposed PillarDB Standard as a solution to address these needs. Garcia Technology Inc team seems very enthusiastic.', 'email', '2026-04-07T03:18:39', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30281, 4094, 2, 'Client expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'internal', '2026-03-25T22:25:53', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30385, 6643, 2, 'Customer discussed the following challenges:
1. We want to ''infuse'' all our services with AI, but we don''t know where to start.

Proposed OmniConnect Proxy as a solution to address these needs.', 'email', '2026-04-08T23:39:32', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30455, 6589, 2, 'Spoke with Lisa Williams regarding their needs: Prospect discussed the following challenges:
1. There''s no ''single source of truth'' for our AI features and our BI reports, so they give different answers.
2. Our competitors are reacting to market changes in seconds, and we''re reacting in days.

Proposed Converge Lakehouse as a solution to address these needs.', 'meeting', '2026-04-08T18:24:31', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30497, 9294, 1, 'Customer discussed the following challenges:
1. We acquired a company with a different sharding key, and we have no way to merge our platforms.
2. Our native database auditing is too performance-intensive, so we have to leave it off.

Proposed OmniConnect Proxy as a solution to address these needs.', 'email', '2026-04-10T16:43:26', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30538, 9307, 2, 'Customer talked about the following challenges:
1. Our developers are busy on our core product; they don''t have time to build these ''nice-to-have'' AI features.

Proposed Neuron Canvas as a solution to address these needs.', 'email', '2026-04-10T17:17:13', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30595, 9145, 1, 'Client went over the following challenges:
1. Our auditors are asking us to ''explain our AI,'' and we have no answer.
2. We need to ''feed'' our AI models with ''fresh'' data, but our data pipelines are slow and batch-based.

Proposed Prometheus AI Factory as a solution to address these needs.', 'email', '2026-04-10T19:42:40', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30642, 9356, 2, 'Client discussed the following challenges:
1. Our QA environment is slow, but we don''t know why, so our tests are unreliable.

Proposed TitanDB Enterprise as a solution to address these needs. Lisa Davis requested additional information.', 'email', '2026-04-10T22:31:42', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30667, 9370, 1, 'Prospect discussed the following challenges:
1. We need to see the query execution plan, but our developers don''t have access or ''know-how''.
2. Our pipelines are inefficient and are costing us a fortune in compute resources.

Proposed CodeCraft DevKit as a solution to address these needs.', 'meeting', '2026-04-10T13:32:44', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30734, 5790, 1, 'Customer discussed the following challenges:
1. We have ''data silos''—our BI team uses the warehouse, and our AI team uses the lake, and they''re looking at different data.
2. Our developers are ''app developers,'' not ''AI/ML engineers''.

Proposed Converge Lakehouse as a solution to address these needs.', 'call', '2026-04-07T21:15:07', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30735, 6443, 2, 'Follow-up with Sarah Davis: Client went over the following challenges:
1. We have ''shadow IT'' apps popping up on unsupported databases, which is a huge risk.

Proposed PillarDB Standard as a solution to address these needs.', 'call', '2026-04-07T00:48:37', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30779, 9417, 1, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'email', '2026-04-10T21:05:33', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30827, 2887, 2, 'Customer discussed the following challenges:
1. We want our AI to cite its sources. ''I got this answer from the ''Employee Handbook, page 52''.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-03-08T19:12:42', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30872, 9460, 2, 'Customer covered the following challenges:
1. We want to add a ''semantic search'' feature to our app, but it''s too complex.

Proposed Synapse AIOps as a solution to address these needs. Scheduled follow-up call for next steps.', 'meeting', '2026-04-10T22:11:17', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (30974, 7160, 2, 'Customer discussed the following challenges:
1. Our data is our biggest asset, but we''re not treating it like one.

Proposed Neuron Canvas as a solution to address these needs.', 'email', '2026-04-10T21:37:39', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (31212, 9613, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs. Miller Education Inc team seems very excited.', 'meeting', '2026-04-10T13:28:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (31294, 2581, 2, 'Client discussed the following challenges:
1. I can see the database CPU is high, but I can''t see which query or which user is causing it.

Proposed ClarityDB Guardian as a solution to address these needs.', 'meeting', '2026-03-10T14:35:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (31308, 6643, 2, 'Meeting notes for Jones Finance Corp: Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'internal', '2026-04-08T17:46:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (31331, 9678, 1, 'Customer discussed the following challenges:
1. Our developers are writing inefficient queries because they don''t understand how the database works.

Proposed OS Guardian Support as a solution to address these needs.', 'email', '2026-04-10T14:23:14', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (31369, 9695, 2, 'Prospect expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'email', '2026-04-10T23:06:16', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (31383, 9703, 1, 'Prospect discussed the following challenges:
1. We have 10 tables for ''prospects'' with different naming conventions (e.g., cust, prospect, acct_prospect).

Proposed CodeCraft DevKit as a solution to address these needs.', 'meeting', '2026-04-10T15:28:05', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (31397, 3806, 2, 'Prospect expressed interest in OmniConnect Proxy for their data infrastructure needs. Action items documented and assigned.', 'email', '2026-03-24T20:32:31', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (31478, 6381, 1, 'Spoke with John Davis regarding their needs: Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'call', '2026-04-07T13:40:29', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (31569, 6391, 2, 'Customer discussed the following challenges:
1. Cross-shard queries are slow, complex, and require a separate aggregation service.

Proposed Neuron Canvas as a solution to address these needs. Johnson Education Ltd team seems very interested.', 'internal', '2026-04-07T20:28:28', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (31661, 9826, 1, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'call', '2026-04-10T13:26:07', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (31755, 9869, 2, 'Customer discussed the following challenges:
1. We need to give our users a ''single data view,'' but our data is in 20 different places.
2. We can''t audit who has accessed our data in the lake.

Proposed Converge Lakehouse as a solution to address these needs.', 'internal', '2026-04-10T10:39:21', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (31840, 6499, 2, 'Customer discussed the following challenges:
1. Our open-source database is just too slow for this new application.

Proposed PillarDB Standard as a solution to address these needs.', 'meeting', '2026-04-08T13:19:59', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32021, 6589, 2, 'Call with Lisa Williams at Williams Technology Co: Customer discussed the following challenges:
1. We spend months building complex data pipelines just to join two tables from two different systems.

Proposed Converge Lakehouse as a solution to address these needs.', 'internal', '2026-04-07T16:41:44', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32037, 5616, 2, 'Client discussed the following challenges:
1. Our internal policy forbids running platformion software with known critical vulnerabilities.
2. We can''t separate ''duty of care'' from ''duty to administer''; our admins see everything.

Proposed TitanDB Enterprise as a solution to address these needs.', 'internal', '2026-04-07T07:49:50', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32062, 6531, 2, 'Prospect covered the following challenges:
1. The cost of one major outage would be 10x the cost of this support subscription.

Proposed OS Guardian Support as a solution to address these needs.', 'meeting', '2026-04-08T17:04:02', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32068, 4094, 1, 'Call with Michael Davis at Johnson Manufacturing Inc: Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'call', '2026-03-29T08:44:24', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32084, 10025, 1, 'Customer talked about the following challenges:
1. The public documentation is good for ''hello world,'' but not for our complex production problem.

Proposed OS Guardian Support as a solution to address these needs. Sarah Johnson requested additional information.', 'call', '2026-04-10T15:31:55', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32210, 2581, 1, 'Call with Sarah Johnson at Smith Healthcare Group: Customer discussed the following challenges:
1. Our team knows the business problem, but they don''t know Python or AI.

Proposed ClarityDB Guardian as a solution to address these needs.', 'internal', '2026-03-31T06:01:56', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32272, 10115, 2, 'Customer covered the following challenges:
1. We are not confident in the quality of patches from the community.
2. We need to scale our database cluster, but the open-source management tools are manual and complex.

Proposed TitanDB Enterprise as a solution to address these needs.', 'email', '2026-04-10T18:41:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32342, 6323, 1, 'Customer went over the following challenges:
1. We keep adding more hardware, but our query performance isn''t improving.
2. We can''t integrate our database into our CI/CD pipeline easily.

Proposed TitanDB Enterprise as a solution to address these needs. Sent proposal documentation via email.', 'internal', '2026-04-10T12:42:23', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32352, 6381, 2, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'internal', '2026-04-10T22:55:23', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32367, 2887, 2, 'Spoke with Michael Smith regarding their needs: Customer talked about the following challenges:
1. Our ''low-code'' tool is great for ''forms over data,'' but it can''t do anything ''smart''.

Proposed Neuron Canvas as a solution to address these needs.', 'call', '2026-03-20T23:42:11', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32508, 6600, 1, 'Spoke with Lisa Garcia regarding their needs: Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'internal', '2026-04-10T13:04:07', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32534, 10227, 1, 'Customer discussed the following challenges:
1. When our primary database fails, our application is down for 30 minutes while we manually repoint it.
2. We are unable to perform database maintenance without coordinated application downtime.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-04-10T17:17:44', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32631, 10278, 1, 'Customer talked about the following challenges:
1. Our open-source database''s auditing is ''all or nothing'' and creates too much noise.
2. The open-source version is ''good enough'' for our internal apps, but not for our core payment processing system.

Proposed TitanDB Enterprise as a solution to address these needs.', 'meeting', '2026-04-10T14:57:13', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32658, 4750, 2, 'Prospect went over the following challenges:
1. We can''t get data from our ''transactional'' databases into our ''AI'' platform easily.
2. We want to add a ''summarization'' feature to our app, but we don''t know how to call an LLM securely.

Proposed Prometheus AI Factory as a solution to address these needs.', 'call', '2025-12-29T11:58:37', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32704, 6427, 1, 'Customer went over the following challenges:
1. Our development frameworks don''t integrate well with the open-source database.

Proposed PillarDB Standard as a solution to address these needs.', 'call', '2026-04-10T00:39:37', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32714, 8705, 2, 'Discussion with Garcia Manufacturing Inc team: Customer discussed the following challenges:
1. We are in Germany (or France, Canada, etc.), and data-residency laws require us to process all data within our country.
2. We can''t enforce data access policies at a granular, query-by-query level.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-04-10T20:28:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32725, 10227, 1, 'Account discussed the following challenges:
1. We have to over-provision our database hardware just to handle the connection load, which is expensive.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-04-10T18:54:01', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32845, 3332, 1, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs. Action items documented and assigned.', 'internal', '2026-04-05T13:12:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32929, 6643, 1, 'Prospect expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'email', '2026-04-07T09:53:57', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (32937, 6085, 1, 'Customer discussed the following challenges:
1. Our data is in a complex data warehouse, and only 3 people in the company know how to query it.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-04-10T23:13:30', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33020, 10424, 37, 'Extended call with Robert Garcia at Garcia Technology Corp covering their Technology infrastructure.

**Call Summary**
Productive discussion covering their core Technology requirements. Robert Garcia led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

**Target Use Cases**
Robert Garcia outlined specific use cases they want to address with ClarityDB Guardian:


_Deal: $9820 | Stage: early | Champion: Robert Garcia_', NULL, '2026-01-29T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33021, 10424, 37, 'Had our first substantive call with Garcia Technology Corp today. Main discussion centered on data management challenges. Robert Garcia mentioned this has been a pain point for over a year. Standard evaluation process. Garcia Technology Corp doing due diligence. Next: Schedule technical demo with their engineering team.', NULL, '2026-02-04T19:27:35.407751', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33022, 10424, 37, 'Comprehensive review session with Robert Garcia regarding ClarityDB Guardian implementation.

**Call Summary**
Extended meeting covering both business and technical aspects. Robert Garcia brought in their architect to validate our approach to data management challenges. Strong interest in our Technology experience.

**Next Steps**
1. Send ClarityDB Guardian technical overview and architecture documentation
2. Schedule demo with Robert Garcia''s engineering team (targeting next week)
3. Share Technology case studies and reference customers
4. Robert Garcia to gather internal requirements from their team

**Key Stakeholders**
- **Robert Garcia** (Primary Contact) - Technical Lead, strong champion, driving the evaluation
- **David** - Director of IT, technical decision maker, needs to sign off on architecture
- **Lisa** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the Head of Platform. Robert Garcia has direct access and influence.

_Deal: $9820 | Stage: early | Champion: Robert Garcia_', NULL, '2026-02-07T06:16:39.914202', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33023, 10424, 37, 'Shared updated quote with revised terms for Garcia Technology Corp.', NULL, '2026-02-12T09:50:29.092248', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33024, 10424, 37, 'Sent quote to Garcia Technology Corp.', NULL, '2026-02-13T16:02:21.665095', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33025, 10424, 37, 'Detailed technical discussion with Garcia Technology Corp team. Key stakeholder: Robert Garcia.

**Call Summary**
Extended meeting covering both business and technical aspects. Robert Garcia brought in their architect to validate our approach to data management challenges. Strong interest in our Technology experience.

**Timeline & Urgency**
Robert Garcia mentioned several timing factors:
- Board meeting next month where they need to present solution
- Integration with their Q2 product launch
- Team capacity available now, may not be later

Urgency is real. We should accelerate our response.

**Target Use Cases**
Robert Garcia outlined specific use cases they want to address with ClarityDB Guardian:


_Deal: $9820 | Stage: early | Champion: Robert Garcia_', NULL, '2026-02-14T11:59:28.081667', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33026, 10424, 37, 'Assigned next steps to account owner and logged in CRM.', NULL, '2026-02-17T07:12:27.908091', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33027, 10424, 37, 'Spoke with CS about support handoff notes.', NULL, '2026-02-24T07:50:35.470429', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33028, 10424, 37, '## Technical Deep-Dive: Garcia Technology Corp

Detailed walkthrough of ClarityDB Guardian capabilities with Garcia Technology Corp''s engineering and business teams. Covered architecture, integration, and roadmap.

### Call Summary
Extended meeting covering both business and technical aspects. Robert Garcia brought in their architect to validate our approach to data management challenges. Strong interest in our Technology experience.

### Pain Points Discussed
Robert Garcia outlined the issues they''re facing with their current approach:


Robert Garcia emphasized that solving these issues is a top priority for their leadership team.

### Competitive Landscape
Competition includes **Databricks** (incumbent) and **Elastic** (also evaluating). We''re differentiated on:
- Native support for their Technology workflows
- More flexible pricing model
- Faster time to value

They had a bad experience with Elastic previously - opportunity to capitalize.

### Key Stakeholders
- **Robert Garcia** (Primary Contact) - Technical Lead, strong champion, driving the evaluation
- **Amanda** - VP of Engineering, technical decision maker, needs to sign off on architecture
- **David** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the VP of Engineering. Robert Garcia has direct access and influence.

### Technical Requirements
- CI/CD pipeline integration
- Container and Kubernetes support
- Audit logging and compliance reporting

### Timeline & Urgency
Robert Garcia mentioned several timing factors:
- Board meeting next month where they need to present solution
- Integration with their Q2 product launch
- Team capacity available now, may not be later

Urgency is real. We should accelerate our response.

---
**Deal Details:** $9820 ARR | **Stage:** middle | **Industry:** Technology
**Champion:** Robert Garcia | **Product:** ClarityDB Guardian', NULL, '2026-02-24T16:52:03.032961', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33029, 10424, 37, 'Voicemail left - Robert Garcia unavailable.', NULL, '2026-03-02T02:39:13.944460', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33030, 10424, 37, 'Detailed technical discussion with Garcia Technology Corp team. Key stakeholder: Robert Garcia.

**Call Summary**
Productive discussion covering their core Technology requirements. Robert Garcia led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

**Next Steps**
1. Prepare custom demo addressing key requirements
2. Schedule reference call with similar Technology customer
3. Send preliminary pricing and packaging options
4. Robert Garcia to arrange meeting with their VP of Engineering

**Timeline & Urgency**
Robert Garcia indicated a target decision date of end of quarter. Key timeline drivers:
- Current contract with existing vendor expires in 90 days
- New fiscal year budget available starting next month
- Technology priority initiative tied to this solution

**Risk:** Delay could push to next budget cycle.

_Deal: $9820 | Stage: middle | Champion: Robert Garcia_', NULL, '2026-03-04T04:19:59.017242', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33031, 10424, 37, 'Good call with Robert Garcia today.', NULL, '2026-03-05T10:11:08.968901', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33032, 10424, 37, 'Demo went well with Garcia Technology Corp. Robert Garcia was engaged, especially around the data management challenges solution. They want to see a POC proposal.', NULL, '2026-03-11T04:30:57.703935', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33033, 10424, 37, 'Sent case study as requested.', NULL, '2026-03-17T03:01:31.849738', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33034, 10424, 37, 'Waiting for legal review.', NULL, '2026-03-18T11:25:25.372079', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33035, 10424, 37, 'Contract review meeting with Garcia Technology Corp legal and Robert Garcia. Minor redlines on SLA terms. Should close by end of month.', NULL, '2026-03-20T13:01:34.447924', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33036, 10424, 37, 'Pricing discussion with Robert Garcia. Deal size around $9820. They''re comparing us to two other vendors. Decision expected in 2 weeks.', NULL, '2026-04-01T22:56:34.598652', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33037, 10424, 37, 'Meeting confirmed for next week.', NULL, '2026-04-06T03:03:54.816205', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33038, 10424, 37, 'Proposal sent to Garcia Technology Corp.', NULL, '2026-04-07T17:07:56.798275', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33039, 10424, 37, 'Detailed technical discussion with Garcia Technology Corp team. Key stakeholder: Robert Garcia.

**Call Summary**
Comprehensive call with Robert Garcia and two other stakeholders from their technical team. Main focus was understanding how ClarityDB Guardian handles data management challenges. Good energy throughout the session.

**Technical Requirements**
- CI/CD pipeline integration
- Container and Kubernetes support
- Audit logging and compliance reporting

**Competitive Landscape**
This is a competitive deal. **Elastic** has existing relationship but Robert Garcia frustrated with their roadmap. **MongoDB** in the mix but lacks Technology expertise.

Our advantages: technical depth, Technology focus, and Robert Garcia as a strong champion.

_Deal: $9820 | Stage: late | Champion: Robert Garcia_', NULL, '2026-04-08T04:06:24.019163', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33040, 10424, 37, 'Call with Garcia Technology Corp team. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Technology requirements. Excellent reception from the Garcia Technology Corp team. They see clear value. Sending summary and action items.', NULL, '2026-04-08T22:09:12.445556', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33041, 10424, 37, 'Call with Garcia Technology Corp team. Deep dive into data management challenges and operational efficiency challenges. Their current workaround is manual and error-prone. Robert Garcia is very enthusiastic about ClarityDB Guardian. Strong champion potential. Next meeting scheduled for next week.', NULL, '2026-04-11T07:54:16.798640', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33042, 10424, 37, 'Discussion with Robert Garcia about next steps. The team is struggling with data management challenges, which is impacting their operations significantly. Excellent reception from the Garcia Technology Corp team. They see clear value. Next meeting scheduled for next week.', NULL, '2026-04-12T01:07:04.050261', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33271, 10443, 19, 'Detailed technical discussion with Miller Technology Systems team. Key stakeholder: Robert Davis.

**Call Summary**
Comprehensive call with Robert Davis and two other stakeholders from their technical team. Main focus was understanding how OmniConnect Proxy handles When our primary database fails, our application is down for 30 minutes while we manually repoint it. in the context of their Security Auditing initiative. Good energy throughout the session.

**Target Use Cases**
The Miller Technology Systems team is targeting the following deployment scenarios:

1. **Security Auditing**
   - Gain complete visibility into every query that hits your database. OmniConnect logs all traffic, allowing security teams to easily audit data access patterns, identify anomalous behavior, and maintain a detailed compliance record, ultimately preventing unauthorized data exposure before it happens.
   - Tied to a strategic initiative from their leadership. Must be in place by end of quarter.
   - Robert Davis confirmed budget is allocated specifically for this use case.

2. **Failover and High Availability**
   - Automatically detect and route traffic away from failed or maintenance-mode database nodes without any application-level changes. This seamless failover ensures your services remain online and operational 24/7, achieving near-zero downtime and upholding critical service level agreements (SLAs).
   - Secondary priority but equally important for their long-term roadmap.
   - Would consolidate multiple point solutions they currently maintain.

**Connection to Pain Points:** Successfully implementing Security Auditing would directly address When our primary database fails, our application is down for 30 minutes while we manually repoint it., which is their biggest operational challenge.

**Timeline & Urgency**
Robert Davis indicated a target decision date of end of quarter. Key timeline drivers:
- Current contract with existing vendor expires in 90 days
- New fiscal year budget available starting next month
- Manufacturing priority initiative tied to this solution

**Risk:** Delay could push to next budget cycle.

_Deal: $56647 | Stage: early | Champion: Robert Davis_', NULL, '2026-02-09T23:14:51.248474', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33272, 10443, 19, 'Rescheduled demo to accommodate their team.', NULL, '2026-02-25T18:26:27.989478', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33273, 10443, 19, 'Productive follow-up session with Miller Technology Systems. The team is struggling with When our primary database fails, our application is down for 30 minutes while we manually repoint it., which is impacting their operations significantly. Robert Davis professional and thorough in their questions. Next: Send detailed proposal and pricing options.', NULL, '2026-03-01T22:52:23.939233', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33274, 10443, 19, 'Productive follow-up session with Miller Technology Systems. Key issue raised: When our primary database fails, our application is down for 30 minutes while we manually repoint it.. They''ve tried other solutions but none addressed their Manufacturing requirements. Encouraging discussion. Next steps agreed upon. Next: Send detailed proposal and pricing options.', NULL, '2026-03-11T20:38:58.174197', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33275, 10443, 19, 'Left voicemail for Robert Davis requesting availability for a short demo.', NULL, '2026-03-13T21:05:23.898474', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33276, 10443, 19, 'Critical negotiation meeting with Miller Technology Systems. Main discussion centered on When our primary database fails, our application is down for 30 minutes while we manually repoint it.. Robert Davis mentioned this has been a pain point for over a year. Robert Davis is very enthusiastic about OmniConnect Proxy. Strong champion potential. Next: Final contract review with legal teams.', NULL, '2026-03-24T18:53:59.405493', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33277, 10443, 19, 'Final technical review with Robert Davis and their team. Main discussion centered on When our primary database fails, our application is down for 30 minutes while we manually repoint it.. Robert Davis mentioned this has been a pain point for over a year. Very positive signals. Miller Technology Systems team aligned on moving forward. Scheduling closing call for end of week.', NULL, '2026-04-15T15:58:10.594548', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33278, 10443, 19, 'Sync with Robert Davis. They''re working through When our primary database fails, our application is down for 30 minutes while we manually repoint it. challenges. OmniConnect Proxy well-positioned to help.', NULL, '2026-04-17T06:26:07.898970', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33342, 10449, 35, 'Had our first substantive call with Davis Retail Solutions today. Deep dive into A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems. and We hit a known bug, but the enterprise version''s hotfix isn''t available for the open-source version.. Their current workaround is manual and error-prone. Meeting went as expected. Following standard sales process. Next: Schedule technical demo with their engineering team.', NULL, '2026-03-24T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33343, 10449, 35, 'Voicemail left - Robert Garcia unavailable.', NULL, '2026-03-24T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33344, 10449, 35, 'Initial discovery meeting with Robert Garcia and their team. The team is struggling with A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems., which is impacting their operations significantly. Meeting went as expected. Following standard sales process. Following up with PillarDB Standard overview deck and case studies.', NULL, '2026-04-02T10:18:54.155046', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33345, 10449, 35, '## Meeting Notes: Davis Retail Solutions

Extended technical and business discussion with Robert Garcia and their team at Davis Retail Solutions. This was a pivotal meeting in the evaluation process.

### Call Summary
Comprehensive call with Robert Garcia and two other stakeholders from their technical team. Main focus was understanding how PillarDB Standard handles A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems. in the context of their Partner Integrations initiative. Good energy throughout the session.

### Pain Points Discussed
Key pain points identified during the discussion with Davis Retail Solutions:

1. **A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems.** - Critical blocker for their growth plans. Current solution can''t scale to meet demand.
2. **We hit a known bug, but the enterprise version''s hotfix isn''t available for the open-source version.** - Related to the first issue. Solving one should help address the other.

Robert Garcia emphasized that solving these issues is a top priority for their leadership team.

### Competitive Landscape
Competition includes **Competitor A** (incumbent) and **Competitor B** (also evaluating). We''re differentiated on:
- Native support for their Education workflows
- More flexible pricing model
- Faster time to value

They had a bad experience with Competitor B previously - opportunity to capitalize.

### Next Steps
1. Send PillarDB Standard technical overview and architecture documentation
2. Schedule demo with Robert Garcia''s engineering team (targeting next week)
3. Share Education case studies and reference customers

### Technical Requirements
- **Primary:** A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems.
- **Secondary:** We hit a known bug, but the enterprise version''s hotfix isn''t available for the open-source version.
- Enterprise-grade security
- 24/7 support availability
- API-first architecture for custom integrations

### Timeline & Urgency
Robert Garcia mentioned several timing factors:
- Board meeting next month where they need to present solution
- Integration with their Q2 product launch
- Team capacity available now, may not be later

Urgency is real. We should accelerate our response.

---
**Deal Details:** $45851 ARR | **Stage:** early | **Industry:** Education
**Champion:** Robert Garcia | **Product:** PillarDB Standard', NULL, '2026-04-19T00:08:37.101398', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33346, 10449, 35, 'Comprehensive review session with Robert Garcia regarding PillarDB Standard implementation.

**Call Summary**
Deep technical conversation with Davis Retail Solutions''s evaluation team. Robert Garcia has done their homework on our platform. Discussion centered on Partner Integrations and how we address A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems. better than their current solution.

**Key Stakeholders**
- **Robert Garcia** (Primary Contact) - Solutions Architect, strong champion, driving the evaluation
- **Mike** - Chief Architect, technical decision maker, needs to sign off on architecture
- **Chris** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the CTO. Robert Garcia has direct access and influence.

_Deal: $45851 | Stage: middle | Champion: Robert Garcia_', NULL, '2026-04-19T05:48:14.187757', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33347, 10449, 35, 'Detailed technical discussion with Davis Retail Solutions team. Key stakeholder: Robert Garcia.

**Call Summary**
Great session with Davis Retail Solutions team. They walked us through their Partner Integrations requirements in detail. Clear alignment between their needs around A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems. and what PillarDB Standard delivers.

**Target Use Cases**
Robert Garcia outlined specific use cases they want to address with PillarDB Standard:

1. **Partner Integrations**
   - Leverage certified connectors for common backup, monitoring, and application development frameworks. This makes it simple to integrate PillarDB Standard into your existing IT landscape, reducing setup time and ensuring compatibility with the tools your team already uses.
   - This is their primary driver for evaluating PillarDB Standard. Robert Garcia estimates this will save their team 15+ hours per week.
   - They''ve tried addressing this with their current solution but hit scaling limitations.

2. **Support for Tier 2 and 3 Applications**
   - Run your important but non-mission-critical applications, such as internal wikis, CMS platforms, or development/testing environments, on a reliable, vendor-backed database. You get professional support and stability without allocating your top-tier budget, ensuring these essential services remain healthy and performant.
   - Complements their primary use case. Once the first is running, this becomes the natural next step.
   - ROI calculations show significant cost savings here.

**Connection to Pain Points:** Successfully implementing Partner Integrations would directly address A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems., which is their biggest operational challenge.

_Deal: $45851 | Stage: middle | Champion: Robert Garcia_', NULL, '2026-04-20T05:44:49.058375', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33348, 10449, 35, 'Productive follow-up session with Davis Retail Solutions. Key issue raised: A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems.. They''ve tried other solutions but none addressed their Education requirements. Robert Garcia engaged throughout the discussion. Scheduling reference call with similar Education customer.', NULL, '2026-05-03T12:59:44.842371', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33349, 10449, 35, 'Brief touch base with Robert Garcia.', NULL, '2026-05-03T19:38:12.046992', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33350, 10449, 35, 'Sent follow-up email - no response yet.', NULL, '2026-05-12T08:40:00.541184', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33351, 10449, 35, 'Sent case study as requested.', NULL, '2026-05-22T21:17:30.165246', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33352, 10449, 35, 'Pre-decision meeting with Robert Garcia and procurement. Key issue raised: A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems.. They''ve tried other solutions but none addressed their Education requirements. Encouraging discussion. Next steps agreed upon. Preparing executive summary for their leadership.', NULL, '2026-05-31T16:53:20.060029', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33353, 10449, 35, 'Contract and pricing discussion with Davis Retail Solutions. Main discussion centered on A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems.. Robert Garcia mentioned this has been a pain point for over a year. Davis Retail Solutions team receptive to our approach. Building momentum. Scheduling closing call for end of week.', NULL, '2026-05-31T18:36:03.172301', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33354, 10449, 35, 'Final technical review with Robert Garcia and their team. Main discussion centered on A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems.. Robert Garcia mentioned this has been a pain point for over a year. Good engagement from Robert Garcia. They see the potential. Next: Final contract review with legal teams.', NULL, '2026-06-05T16:51:11.556072', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33355, 10449, 35, 'Critical negotiation meeting with Davis Retail Solutions. Main discussion centered on A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems.. Robert Garcia mentioned this has been a pain point for over a year. Good engagement from Robert Garcia. They see the potential. Next: Final contract review with legal teams.', NULL, '2026-06-15T00:05:43.137974', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33356, 10449, 35, 'Demo went well with Davis Retail Solutions.', NULL, '2026-06-19T11:30:32.234961', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33357, 10449, 35, 'Call with Davis Retail Solutions team. The team is struggling with A security breach in our Tier 2 app could still be a gateway to our Tier 1 systems., which is impacting their operations significantly. Davis Retail Solutions team receptive to our approach. Building momentum. Will follow up with additional materials.', NULL, '2026-06-21T21:53:26.872149', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33567, 10466, 49, 'Initial discovery meeting with Jane Jones and their team. Key issue raised: The public documentation is good for ''hello world,'' but not for our complex production problem.. They''ve tried other solutions but none addressed their Finance requirements. Meeting went as expected. Following standard sales process. Following up with OS Guardian Support overview deck and case studies.', NULL, '2026-02-13T14:45:06.566275', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33568, 10466, 49, 'Sent ROI calculator to Jane Jones.', NULL, '2026-02-16T10:12:29.318957', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33569, 10466, 49, 'Detailed technical discussion with Jones Healthcare LLC team. Key stakeholder: Jane Jones.

**Call Summary**
Extended meeting covering both business and technical aspects. Jane Jones brought in their architect to validate our approach to Training Material. Strong interest in how we solve The public documentation is good for ''hello world,'' but not for our complex production problem. for Finance customers.

**Next Steps**
1. Send OS Guardian Support technical overview and architecture documentation
2. Schedule demo with Jane Jones''s engineering team (targeting next week)
3. Share Finance case studies and reference customers
4. Jane Jones to gather internal requirements from their team

**Competitive Landscape**
Jones Healthcare LLC is also evaluating **FIS** and **Refinitiv**. Our key differentiators:
- Superior handling of The public documentation is good for ''hello world,'' but not for our complex production problem.
- Stronger Finance-specific features
- Better customer support reputation

Jane Jones mentioned they''ve had issues with FIS''s implementation complexity in the past.

_Deal: $13566 | Stage: early | Champion: Jane Jones_', NULL, '2026-02-28T00:10:40.251463', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33570, 10466, 49, 'Follow-up call with Jane Jones. They''ve shared OS Guardian Support with their VP. Main concerns are around The public documentation is good for ''hello world,'' but not for our complex production problem.. Addressing in next meeting.', NULL, '2026-03-06T13:05:30.211224', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33571, 10466, 49, 'Technical deep-dive with Jones Healthcare LLC''s engineering team. Good discussion on The public documentation is good for ''hello world,'' but not for our complex production problem. and We keep ''rediscovering'' solutions to problems our team has already solved.. Jane Jones asking for reference customers.', NULL, '2026-03-12T00:41:49.013217', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33572, 10466, 49, 'Waiting for Jones Healthcare LLC decision.', NULL, '2026-03-15T13:38:45.545996', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33573, 10466, 49, 'Negotiation call with Jane Jones and their procurement. Working through volume discount structure for $13566 deal.', NULL, '2026-03-23T04:37:53.761765', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33574, 10466, 49, 'Moved meeting to next Thursday.', NULL, '2026-03-24T12:26:11.335020', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33575, 10466, 49, 'Final technical validation with Jones Healthcare LLC. All concerns addressed including The public documentation is good for ''hello world,'' but not for our complex production problem.. Jane Jones pushing for approval this quarter.', NULL, '2026-04-02T13:10:20.717678', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33576, 10466, 49, 'Discussion with Jane Jones about next steps. The team is struggling with The public documentation is good for ''hello world,'' but not for our complex production problem., which is impacting their operations significantly. Excellent reception from the Jones Healthcare LLC team. They see clear value. Next meeting scheduled for next week.', NULL, '2026-04-12T04:09:55.929510', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (33577, 10466, 49, 'Meeting with Jones Healthcare LLC team went well. Jane Jones is our champion, pushing internally. Deal progressing.', NULL, '2026-04-15T18:33:12.542381', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (35185, 10599, 19, 'Initial discovery meeting with Jane Smith and their team. Main discussion centered on Security code reviews are slow and can''t catch every possible injection vector.. Jane Smith mentioned this has been a pain point for over a year. Meeting went as expected. Following standard sales process. Setting up intro call with our solutions architect.', NULL, '2026-01-10T21:36:40.513617', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (35186, 10599, 19, 'Comprehensive review session with Jane Smith regarding OmniConnect Proxy implementation.

**Call Summary**
Extended meeting covering both business and technical aspects. Jane Smith brought in their architect to validate our approach to Failover and High Availability. Strong interest in how we solve Security code reviews are slow and can''t catch every possible injection vector. for Technology customers.

**Competitive Landscape**
Competition includes **Snowflake** (incumbent) and **Databricks** (also evaluating). We''re differentiated on:
- Native support for their Technology workflows
- More flexible pricing model
- Faster time to value

They had a bad experience with Databricks previously - opportunity to capitalize.

_Deal: $99612 | Stage: middle | Champion: Jane Smith_', NULL, '2026-01-17T18:24:45.911547', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (35187, 10599, 19, 'Technical deep-dive with Miller Retail Inc''s engineering team. Good discussion on Security code reviews are slow and can''t catch every possible injection vector. and Our serverless functions are overwhelming the database by opening thousands of short-lived connections.. Jane Smith asking for reference customers.', NULL, '2026-02-18T12:32:49.858838', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (35188, 10599, 19, 'Scheduled callback window; expecting response this week.', NULL, '2026-03-18T00:23:17.137574', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (35189, 10599, 19, 'Follow-up scheduled with Jane Smith.', NULL, '2026-04-19T11:36:27.463285', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36985, 10727, 29, 'Discovery session with Jones Manufacturing Group team. Primary pain point is It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs.. Robert Brown to loop in their technical lead for deeper dive.', NULL, '2025-03-07T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36986, 10727, 29, '## Meeting Notes: Jones Manufacturing Group

Extended technical and business discussion with Robert Brown and their team at Jones Manufacturing Group. This was a pivotal meeting in the evaluation process.

### Call Summary
Extended meeting covering both business and technical aspects. Robert Brown brought in their architect to validate our approach to Data Governance. Strong interest in how we solve It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs. for Manufacturing customers.

### Next Steps
1. Send Converge Lakehouse technical overview and architecture documentation
2. Schedule demo with Robert Brown''s engineering team (targeting next week)
3. Share Manufacturing case studies and reference customers
4. Robert Brown to gather internal requirements from their team

### Competitive Landscape
Jones Manufacturing Group is also evaluating **Dassault** and **Rockwell**. Our key differentiators:
- Superior handling of It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs.
- Stronger Manufacturing-specific features
- Better customer support reputation

Robert Brown mentioned they''ve had issues with Dassault''s implementation complexity in the past.

### Technical Requirements
- **Primary:** It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs.
- **Secondary:** We can''t ingest and query our IoT sensor data fast enough.
- IoT device integration
- Real-time production monitoring
- API-first architecture for custom integrations

---
**Deal Details:** $59236 ARR | **Stage:** early | **Industry:** Manufacturing
**Champion:** Robert Brown | **Product:** Converge Lakehouse', NULL, '2025-04-30T16:54:16.980702', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36987, 10727, 29, 'Good intro meeting with Jones Manufacturing Group. Robert Brown outlined their Manufacturing challenges including It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs.. Sending over technical overview.', NULL, '2025-05-10T19:00:30.107160', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36988, 10727, 29, 'Productive follow-up session with Jones Manufacturing Group. Deep dive into It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs. and We can''t ingest and query our IoT sensor data fast enough.. Their current workaround is manual and error-prone. Meeting went as expected. Following standard sales process. Will prepare custom demo addressing It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs..', NULL, '2025-06-29T06:41:09.335817', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36989, 10727, 29, 'Continued evaluation discussions with Robert Brown. Key issue raised: It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs.. They''ve tried other solutions but none addressed their Manufacturing requirements. Jones Manufacturing Group team receptive to our approach. Building momentum. Will prepare custom demo addressing It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs..', NULL, '2025-07-13T22:49:50.969536', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36990, 10727, 29, 'Detailed technical discussion with Jones Manufacturing Group team. Key stakeholder: Robert Brown.

**Call Summary**
Comprehensive call with Robert Brown and two other stakeholders from their technical team. Main focus was understanding how Converge Lakehouse handles It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs. in the context of their Data Governance initiative. Good energy throughout the session.

**Target Use Cases**
Robert Brown outlined specific use cases they want to address with Converge Lakehouse:

1. **Data Governance**
   - Implement a single, unified governance model for all your data assets, including structured tables and raw files. You can define access policies, mask sensitive PII, and audit data lineage from a central control plane, ensuring your data is both secure and compliant across the organization.
   - Critical for their Manufacturing operations. Current workaround involves manual processes that don''t scale.
   - Robert Brown''s team has been pushing for a solution here for 6+ months.

2. **Business Insights**
   - Empower business users to explore and analyze all of the organization''s data, not just a subset that''s been moved to a warehouse. This "data democratization" allows teams to ask new questions and find insights faster, leading to more agile, data-driven decision-making.
   - Complements their primary use case. Once the first is running, this becomes the natural next step.
   - ROI calculations show significant cost savings here.

**Connection to Pain Points:** Successfully implementing Data Governance would directly address It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs., which is their biggest operational challenge.

**Competitive Landscape**
Jones Manufacturing Group is also evaluating **Rockwell** and **Dassault**. Our key differentiators:
- Superior handling of It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs.
- Stronger Manufacturing-specific features
- Better customer support reputation

Robert Brown mentioned they''ve had issues with Rockwell''s implementation complexity in the past.

_Deal: $59236 | Stage: middle | Champion: Robert Brown_', NULL, '2025-09-03T19:01:25.431882', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36991, 10727, 29, 'Left VM for Robert Brown.', NULL, '2025-10-09T05:56:05.659806', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36992, 10727, 29, 'Demo went well with Jones Manufacturing Group. Robert Brown was engaged, especially around the It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs. solution. They want to see a POC proposal.', NULL, '2025-10-29T20:49:07.105512', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36993, 10727, 29, 'Contract review meeting with Jones Manufacturing Group legal and Robert Brown. Minor redlines on SLA terms. Should close by end of month.', NULL, '2025-11-30T04:26:18.080404', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36994, 10727, 29, 'Sent introduction email and product overview for Converge Lakehouse to Robert Brown.', NULL, '2025-12-02T22:44:50.866601', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36995, 10727, 29, 'Requested return call to finalize PO details.', NULL, '2026-01-16T00:05:56.008789', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36996, 10727, 29, 'Detailed technical discussion with Jones Manufacturing Group team. Key stakeholder: Robert Brown.

**Call Summary**
Extended meeting covering both business and technical aspects. Robert Brown brought in their architect to validate our approach to Data Governance. Strong interest in how we solve It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs. for Manufacturing customers.

**Next Steps**
1. Follow up with additional materials requested
2. Schedule next call with Robert Brown
3. Send meeting summary and action items

_Deal: $59236 | Stage: close | Champion: Robert Brown_', NULL, '2026-04-11T16:05:51.360610', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (36997, 10727, 29, 'Call with Robert Brown at Jones Manufacturing Group. Discussed It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs. and next steps. Following up with additional materials.', NULL, '2026-04-19T11:37:45.342065', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37026, 10730, 10, 'Follow-up scheduled with Lisa Williams.', NULL, '2025-02-14T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37027, 10730, 10, 'Follow-up call with Lisa Williams. They''ve shared CodeCraft DevKit with their VP. Main concerns are around A user is complaining the app is slow, but we don''t know if it''s the app, the network, or the database.. Addressing in next meeting.', NULL, '2025-03-12T08:07:49.791858', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37028, 10730, 10, 'Productive follow-up session with Garcia Education Systems. Key issue raised: A user is complaining the app is slow, but we don''t know if it''s the app, the network, or the database.. They''ve tried other solutions but none addressed their Education requirements. Garcia Education Systems team receptive to our approach. Building momentum. Scheduling reference call with similar Education customer.', NULL, '2025-04-02T15:57:45.807453', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37029, 10730, 10, 'Voicemail left to remind Lisa Williams about required onboarding documents.', NULL, '2025-04-28T15:59:53.654133', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37030, 10730, 10, 'Lisa Williams is reviewing internally.', NULL, '2025-05-15T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37155, 10738, 31, 'Extended call with David Jones at Smith Technology Systems covering their Finance infrastructure.

**Call Summary**
Deep technical conversation with Smith Technology Systems''s evaluation team. David Jones has done their homework on our platform. Discussion centered on Support on a Budget and how we address We want to connect our monitoring tools to this database, but there''s no official connector. better than their current solution.

**Timeline & Urgency**
David Jones mentioned several timing factors:
- Board meeting next month where they need to present solution
- Integration with their Q2 product launch
- Team capacity available now, may not be later

Urgency is real. We should accelerate our response.

_Deal: $92472 | Stage: early | Champion: David Jones_', NULL, '2025-03-11T10:14:34.225626', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37156, 10738, 31, 'First call with David Jones. They found us through a Finance conference. Main interest is solving We want to connect our monitoring tools to this database, but there''s no official connector.. Demo scheduled.', NULL, '2025-03-11T20:55:26.042588', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37157, 10738, 31, 'Meeting confirmed for next week.', NULL, '2025-03-13T17:24:21.269550', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37158, 10738, 31, 'Proposal sent to Smith Technology Systems.', NULL, '2025-03-15T22:37:31.648902', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37159, 10738, 31, 'Technical deep-dive with Smith Technology Systems''s engineering team. Good discussion on We want to connect our monitoring tools to this database, but there''s no official connector. and We don''t need 15-minute response times, but we can''t wait 3 days for a forum reply.. David Jones asking for reference customers.', NULL, '2025-04-04T01:06:46.134289', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37160, 10738, 31, 'Productive follow-up session with Smith Technology Systems. Key issue raised: We want to connect our monitoring tools to this database, but there''s no official connector.. They''ve tried other solutions but none addressed their Finance requirements. Meeting went as expected. Following standard sales process. Scheduling reference call with similar Finance customer.', NULL, '2025-04-04T14:50:46.674909', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37161, 10738, 31, 'Productive session with Smith Technology Systems. Walked through architecture for handling We want to connect our monitoring tools to this database, but there''s no official connector.. David Jones impressed with our Finance experience.', NULL, '2025-04-07T20:39:48.722019', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37162, 10738, 31, 'Called and left voicemail asking David Jones to confirm receipt of the proposal addendum.', NULL, '2025-04-12T07:32:49.208275', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37163, 10738, 31, 'Sent quote to Smith Technology Systems.', NULL, '2025-04-15T08:02:03.402500', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37164, 10738, 31, 'Left voicemail requesting updated purchase timeline.', NULL, '2025-04-27T11:14:11.917379', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37165, 10738, 31, 'Detailed technical discussion with Smith Technology Systems team. Key stakeholder: David Jones.

**Call Summary**
Productive discussion covering their Support on a Budget requirements. David Jones led the conversation with clear priorities around solving We want to connect our monitoring tools to this database, but there''s no official connector.. The team was engaged and asked detailed questions about how PillarDB Standard supports Access our professional 8x5 business-hour support team for troubleshooting, bug resolution, and best-practice guidance. This provides a crucial safety net for your production systems at a cost-effective price, giving you expert help when you need it most without paying for 24/7 critical coverage..

**Target Use Cases**
Key use cases driving this evaluation at Smith Technology Systems:

1. **Support on a Budget**
   - Access our professional 8x5 business-hour support team for troubleshooting, bug resolution, and best-practice guidance. This provides a crucial safety net for your production systems at a cost-effective price, giving you expert help when you need it most without paying for 24/7 critical coverage.
   - Tied to a strategic initiative from their leadership. Must be in place by end of quarter.
   - David Jones confirmed budget is allocated specifically for this use case.

2. **Bugfixes**
   - Receive timely, pre-tested bugfixes for common issues, resolving glitches and stability problems faster than community-supported versions. This saves your team valuable time they would otherwise spend diagnosing and patching issues themselves, allowing them to focus on new development.
   - Complements their primary use case. Once the first is running, this becomes the natural next step.
   - ROI calculations show significant cost savings here.

**Why This Matters:** The Support on a Budget use case is specifically designed to solve We want to connect our monitoring tools to this database, but there''s no official connector. - the core issue David Jones raised in our first conversation.

**Timeline & Urgency**
Evaluation timeline shared by David Jones:
- Technical validation: Next 2 weeks
- Final vendor selection: End of month
- Contract negotiation: Following 2 weeks
- Target go-live: Within 60 days of signing

This is a real timeline - Smith Technology Systems''s VP has made this a priority.

_Deal: $92472 | Stage: late | Champion: David Jones_', NULL, '2025-05-03T21:05:29.889400', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37166, 10738, 31, 'Called David Jones; left detailed voicemail about next steps.', NULL, '2025-05-14T00:56:53.907102', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37167, 10738, 31, 'Critical negotiation meeting with Smith Technology Systems. Deep dive into We want to connect our monitoring tools to this database, but there''s no official connector. and We don''t need 15-minute response times, but we can''t wait 3 days for a forum reply.. Their current workaround is manual and error-prone. Smith Technology Systems team receptive to our approach. Building momentum. Preparing executive summary for their leadership.', NULL, '2025-05-14T09:46:08.735030', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37168, 10738, 31, 'Sent email re: PillarDB Standard demo.', NULL, '2025-05-17T05:56:30.909421', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37169, 10738, 31, 'Sync with David Jones. They''re working through We want to connect our monitoring tools to this database, but there''s no official connector. challenges. PillarDB Standard well-positioned to help.', NULL, '2025-05-26T06:27:17.425178', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37170, 10738, 31, 'Discussion with David Jones about next steps. Key issue raised: We want to connect our monitoring tools to this database, but there''s no official connector.. They''ve tried other solutions but none addressed their Finance requirements. Encouraging discussion. Next steps agreed upon. Next meeting scheduled for next week.', NULL, '2025-05-31T04:13:45.719100', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37968, 10795, 34, 'Introductory call with Lisa Brown to understand their needs. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Technology requirements. Lisa Brown engaged throughout the discussion. Setting up intro call with our solutions architect.', NULL, '2025-02-11T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37969, 10795, 34, 'Brief touch base with Lisa Brown.', NULL, '2025-05-15T07:02:28.801965', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37970, 10795, 34, 'Extended call with Lisa Brown at Jones Finance Group covering their Technology infrastructure.

**Call Summary**
Productive discussion covering their core Technology requirements. Lisa Brown led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

**Competitive Landscape**
Jones Finance Group is also evaluating **Snowflake** and **Databricks**. Our key differentiators:
- Superior handling of scaling challenges
- Stronger Technology-specific features
- Better customer support reputation

Lisa Brown mentioned they''ve had issues with Snowflake''s implementation complexity in the past.

_Deal: $97770 | Stage: middle | Champion: Lisa Brown_', NULL, '2025-08-04T20:19:12.201209', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37971, 10795, 34, '## Call Summary: Jones Finance Group

Comprehensive review session covering all aspects of their Technology requirements. Multiple stakeholders present including Lisa Brown.

### Call Summary
Extended meeting covering both business and technical aspects. Lisa Brown brought in their architect to validate our approach to data management challenges. Strong interest in our Technology experience.

### Key Stakeholders
- **Lisa Brown** (Primary Contact) - Engineering Manager, strong champion, driving the evaluation
- **Chris** - CTO, technical decision maker, needs to sign off on architecture
- **David** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the Director of IT. Lisa Brown has direct access and influence.

### Technical Requirements
- CI/CD pipeline integration
- Container and Kubernetes support
- Multi-region deployment support

### Target Use Cases
The Jones Finance Group team is targeting the following deployment scenarios:


---
**Deal Details:** $97770 ARR | **Stage:** late | **Industry:** Technology
**Champion:** Lisa Brown | **Product:** TitanDB Enterprise', NULL, '2026-02-13T11:34:17.377920', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (37972, 10795, 34, 'Discussion with Lisa Brown about next steps. Deep dive into data management challenges and operational efficiency challenges. Their current workaround is manual and error-prone. Jones Finance Group leaning toward competitor. Need executive engagement. Sending summary and action items.', NULL, '2026-04-09T04:25:51.777596', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (38049, 10803, 16, 'Extended call with John Davis at Miller Technology Co covering their Finance infrastructure.

**Call Summary**
Deep technical conversation with Miller Technology Co''s evaluation team. John Davis has done their homework on our platform. Discussion centered on Natural Language Access to Data Assets and how we address All our innovation is ''top-down''; we want to enable ''bottom-up'' innovation from our business teams. better than their current solution.

**Technical Requirements**
- **Primary:** All our innovation is ''top-down''; we want to enable ''bottom-up'' innovation from our business teams.
- **Secondary:** We want to empower our ''power users'' in Excel to build AI models.
- SOC 2 Type II certification
- PCI-DSS compliance
- Multi-region deployment support

**Timeline & Urgency**
John Davis indicated a target decision date of end of quarter. Key timeline drivers:
- Current contract with existing vendor expires in 90 days
- New fiscal year budget available starting next month
- Finance priority initiative tied to this solution

**Risk:** Delay could push to next budget cycle.

_Deal: $3576 | Stage: early | Champion: John Davis_', NULL, '2025-03-07T03:32:12.001709', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (38050, 10803, 16, 'On hold pending internal review.', NULL, '2025-03-31T07:49:16.697642', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (38051, 10803, 16, 'Productive session with Miller Technology Co. Walked through architecture for handling All our innovation is ''top-down''; we want to enable ''bottom-up'' innovation from our business teams.. John Davis impressed with our Finance experience.', NULL, '2025-04-14T10:46:52.320672', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (38052, 10803, 16, 'Pre-decision meeting with John Davis and procurement. Deep dive into All our innovation is ''top-down''; we want to enable ''bottom-up'' innovation from our business teams. and We want to empower our ''power users'' in Excel to build AI models.. Their current workaround is manual and error-prone. Encouraging discussion. Next steps agreed upon. Next: Final contract review with legal teams.', NULL, '2025-04-25T14:01:57.824485', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (38053, 10803, 16, 'Pricing discussion with John Davis. Deal size around $3576. They''re comparing us to two other vendors. Decision expected in 2 weeks.', NULL, '2025-05-12T11:34:47.642389', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (38054, 10803, 16, 'Detailed technical discussion with Miller Technology Co team. Key stakeholder: John Davis.

**Call Summary**
Deep technical conversation with Miller Technology Co''s evaluation team. John Davis has done their homework on our platform. Discussion centered on Natural Language Access to Data Assets and how we address All our innovation is ''top-down''; we want to enable ''bottom-up'' innovation from our business teams. better than their current solution.

**Target Use Cases**
John Davis outlined specific use cases they want to address with Neuron Canvas:

1. **Natural Language Access to Data Assets**
   - Build a chat interface that sits on top of your customer database, allowing a support agent to simply ask, "What was John Smith''s last order and shipping status?" The AI retrieves the information from multiple systems and provides a single, concise answer, dramatically improving support efficiency.
   - Tied to a strategic initiative from their leadership. Must be in place by end of quarter.
   - John Davis confirmed budget is allocated specifically for this use case.

2. **Building a RAG App**
   - Visually construct a sophisticated Retrieval-Augmented Generation (RAG) application in hours, not weeks. You can easily connect your internal knowledge base (e.g., SharePoint, Confluence) so that your AI chatbot can answer questions based on your company''s proprietary documents, ensuring responses are accurate and context-aware.
   - Secondary priority but equally important for their long-term roadmap.
   - Would consolidate multiple point solutions they currently maintain.

**Why This Matters:** The Natural Language Access to Data Assets use case is specifically designed to solve All our innovation is ''top-down''; we want to enable ''bottom-up'' innovation from our business teams. - the core issue John Davis raised in our first conversation.

**Competitive Landscape**
Miller Technology Co is also evaluating **Bloomberg** and **Temenos**. Our key differentiators:
- Superior handling of All our innovation is ''top-down''; we want to enable ''bottom-up'' innovation from our business teams.
- Stronger Finance-specific features
- Better customer support reputation

John Davis mentioned they''ve had issues with Bloomberg''s implementation complexity in the past.

_Deal: $3576 | Stage: close | Champion: John Davis_', NULL, '2025-06-05T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39694, 10937, 7, 'Had our first substantive call with Williams Technology Solutions today. Key issue raised: We need a repeatable, automated pipeline to ''process'' data for AI model training.. They''ve tried other solutions but none addressed their Education requirements. Meeting went as expected. Following standard sales process. Next: Schedule technical demo with their engineering team.', NULL, '2025-10-03T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39695, 10937, 7, 'Awaiting callback from David Jones to confirm scope.', NULL, '2025-10-03T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39696, 10937, 7, 'David Jones is reviewing internally.', NULL, '2025-10-21T09:26:08.999338', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39697, 10937, 7, 'Demo scheduled for Friday.', NULL, '2025-10-21T19:02:55.429817', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39698, 10937, 7, 'No update - following normal timeline.', NULL, '2025-10-29T16:28:47.027421', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39699, 10937, 7, 'Demo and technical discussion with David Jones''s team. Key issue raised: We need a repeatable, automated pipeline to ''process'' data for AI model training.. They''ve tried other solutions but none addressed their Education requirements. David Jones engaged throughout the discussion. Will prepare custom demo addressing We need a repeatable, automated pipeline to ''process'' data for AI model training..', NULL, '2025-10-31T00:42:16.712562', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39700, 10937, 7, 'Extended call with David Jones at Williams Technology Solutions covering their Education infrastructure.

**Call Summary**
Great session with Williams Technology Solutions team. They walked us through their Enable Developers to Add Features (Modernize) requirements in detail. Clear alignment between their needs around We need a repeatable, automated pipeline to ''process'' data for AI model training. and what Prometheus AI Factory delivers.

**Timeline & Urgency**
Evaluation timeline shared by David Jones:
- Technical validation: Next 2 weeks
- Final vendor selection: End of month
- Contract negotiation: Following 2 weeks
- Target go-live: Within 60 days of signing

This is a real timeline - Williams Technology Solutions''s VP has made this a priority.

**Pain Points Discussed**
Key pain points identified during the discussion with Williams Technology Solutions:

1. **We need a repeatable, automated pipeline to ''process'' data for AI model training.** - Impacting customer satisfaction and SLA compliance. They''ve had multiple incidents this quarter.
2. **We need full control over the entire AI stack, from the hardware to the model, for security and compliance.** - Secondary but growing concern. They anticipate this becoming critical in Q3.

Budget has been allocated for this initiative. They need a solution in place before end of fiscal year.

_Deal: $3230 | Stage: middle | Champion: David Jones_', NULL, '2025-11-03T13:32:35.506789', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39701, 10937, 7, 'Comprehensive review session with David Jones regarding Prometheus AI Factory implementation.

**Call Summary**
Extended meeting covering both business and technical aspects. David Jones brought in their architect to validate our approach to Enable Developers to Add Features (Modernize). Strong interest in how we solve We need a repeatable, automated pipeline to ''process'' data for AI model training. for Education customers.

**Competitive Landscape**
Williams Technology Solutions is also evaluating **Competitor A** and **Competitor B**. Our key differentiators:
- Superior handling of We need a repeatable, automated pipeline to ''process'' data for AI model training.
- Stronger Education-specific features
- Better customer support reputation

David Jones mentioned they''ve had issues with Competitor A''s implementation complexity in the past.

_Deal: $3230 | Stage: middle | Champion: David Jones_', NULL, '2025-11-11T09:07:50.138094', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39702, 10937, 7, 'Demo and technical discussion with David Jones''s team. Key issue raised: We need a repeatable, automated pipeline to ''process'' data for AI model training.. They''ve tried other solutions but none addressed their Education requirements. David Jones engaged throughout the discussion. Scheduling reference call with similar Education customer.', NULL, '2025-11-15T10:55:33.284095', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39703, 10937, 7, 'Comprehensive review session with David Jones regarding Prometheus AI Factory implementation.

**Call Summary**
Extended meeting covering both business and technical aspects. David Jones brought in their architect to validate our approach to Enable Developers to Add Features (Modernize). Strong interest in how we solve We need a repeatable, automated pipeline to ''process'' data for AI model training. for Education customers.

**Key Stakeholders**
- **David Jones** (Primary Contact) - Engineering Manager, strong champion, driving the evaluation
- **Mike** - VP of Engineering, technical decision maker, needs to sign off on architecture
- **David** - Procurement lead, will handle contract negotiations

Economic buyer appears to be the Director of IT. David Jones has direct access and influence.

_Deal: $3230 | Stage: middle | Champion: David Jones_', NULL, '2025-11-16T23:58:41.548581', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39704, 10937, 7, 'Synced with marketing for co-branded materials.', NULL, '2025-11-23T15:02:37.512640', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39705, 10937, 7, 'Critical negotiation meeting with Williams Technology Solutions. The team is struggling with We need a repeatable, automated pipeline to ''process'' data for AI model training., which is impacting their operations significantly. Positive vibes from the meeting. David Jones supportive. Preparing executive summary for their leadership.', NULL, '2025-11-25T12:19:11.414126', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39706, 10937, 7, 'Contract and pricing discussion with Williams Technology Solutions. The team is struggling with We need a repeatable, automated pipeline to ''process'' data for AI model training., which is impacting their operations significantly. Good engagement from David Jones. They see the potential. Next: Final contract review with legal teams.', NULL, '2025-11-26T19:19:03.219890', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39707, 10937, 7, 'Documented risk items and flagged for leadership review.', NULL, '2025-12-12T03:15:25.004045', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39708, 10937, 7, 'Final technical review with David Jones and their team. Key issue raised: We need a repeatable, automated pipeline to ''process'' data for AI model training.. They''ve tried other solutions but none addressed their Education requirements. Williams Technology Solutions team receptive to our approach. Building momentum. Preparing executive summary for their leadership.', NULL, '2025-12-20T08:37:24.029786', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39709, 10937, 7, 'Comprehensive review session with David Jones regarding Prometheus AI Factory implementation.

**Call Summary**
Productive discussion covering their Enable Developers to Add Features (Modernize) requirements. David Jones led the conversation with clear priorities around solving We need a repeatable, automated pipeline to ''process'' data for AI model training.. The team was engaged and asked detailed questions about how Prometheus AI Factory supports Empower your existing application developers to easily infuse their apps with powerful AI features via simple API calls. A developer can add capabilities like summarization, semantic search, or anomaly detection to a legacy application, modernizing the user experience without needing to be a data science expert..

**Timeline & Urgency**
David Jones indicated a target decision date of end of quarter. Key timeline drivers:
- Current contract with existing vendor expires in 90 days
- New fiscal year budget available starting next month
- Education priority initiative tied to this solution

**Risk:** Delay could push to next budget cycle.

_Deal: $3230 | Stage: late | Champion: David Jones_', NULL, '2025-12-22T04:16:57.072756', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39710, 10937, 7, 'Comprehensive review session with David Jones regarding Prometheus AI Factory implementation.

**Call Summary**
Deep technical conversation with Williams Technology Solutions''s evaluation team. David Jones has done their homework on our platform. Discussion centered on Enable Developers to Add Features (Modernize) and how we address We need a repeatable, automated pipeline to ''process'' data for AI model training. better than their current solution.

**Competitive Landscape**
Competition includes **Competitor A** (incumbent) and **Competitor B** (also evaluating). We''re differentiated on:
- Native support for their Education workflows
- More flexible pricing model
- Faster time to value

They had a bad experience with Competitor B previously - opportunity to capitalize.

**Pain Points Discussed**
David Jones outlined the issues they''re facing with their current approach:

1. **We need a repeatable, automated pipeline to ''process'' data for AI model training.** - Impacting customer satisfaction and SLA compliance. They''ve had multiple incidents this quarter.
2. **We need full control over the entire AI stack, from the hardware to the model, for security and compliance.** - Secondary but growing concern. They anticipate this becoming critical in Q3.

David Jones emphasized that solving these issues is a top priority for their leadership team.

_Deal: $3230 | Stage: late | Champion: David Jones_', NULL, '2025-12-23T19:58:21.796250', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39711, 10937, 7, 'Discussion with David Jones about next steps. Main discussion centered on We need a repeatable, automated pipeline to ''process'' data for AI model training.. David Jones mentioned this has been a pain point for over a year. Good engagement from David Jones. They see the potential. Will follow up with additional materials.', NULL, '2025-12-30T07:19:53.490304', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39712, 10937, 7, 'Extended call with David Jones at Williams Technology Solutions covering their Education infrastructure.

**Call Summary**
Extended meeting covering both business and technical aspects. David Jones brought in their architect to validate our approach to Enable Developers to Add Features (Modernize). Strong interest in how we solve We need a repeatable, automated pipeline to ''process'' data for AI model training. for Education customers.

**Technical Requirements**
- **Primary:** We need a repeatable, automated pipeline to ''process'' data for AI model training.
- **Secondary:** We need full control over the entire AI stack, from the hardware to the model, for security and compliance.
- Enterprise-grade security
- 24/7 support availability
- High availability (99.9%+ uptime requirement)

_Deal: $3230 | Stage: close | Champion: David Jones_', NULL, '2025-12-31T02:10:43.194126', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39738, 10942, 34, 'First call with Robert Williams. They found us through a Finance conference. Main interest is solving Our developers are spending 30% of their time just writing boilerplate SQL and CREATE scripts.. Demo scheduled.', NULL, '2025-11-29T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39739, 10942, 34, 'Had our first substantive call with Williams Healthcare Systems today. Key issue raised: Our developers are spending 30% of their time just writing boilerplate SQL and CREATE scripts.. They''ve tried other solutions but none addressed their Finance requirements. Standard evaluation process. Williams Healthcare Systems doing due diligence. Setting up intro call with our solutions architect.', NULL, '2025-12-02T16:50:05.248832', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39740, 10942, 34, 'Technical review completed.', NULL, '2025-12-19T09:17:20.277442', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39741, 10942, 34, 'Called and left voicemail asking Robert Williams to confirm receipt of the proposal addendum.', NULL, '2025-12-26T22:32:15.826068', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39742, 10942, 34, 'Initial discovery meeting with Robert Williams and their team. Key issue raised: Our developers are spending 30% of their time just writing boilerplate SQL and CREATE scripts.. They''ve tried other solutions but none addressed their Finance requirements. Meeting went as expected. Following standard sales process. Next: Schedule technical demo with their engineering team.', NULL, '2025-12-30T01:39:07.441219', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39743, 10942, 34, 'Good call with Robert Williams today.', NULL, '2026-01-03T14:21:41.261303', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39744, 10942, 34, 'Scheduled technical deep-dive with SE and Robert Williams.', NULL, '2026-01-13T22:11:35.156983', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39745, 10942, 34, 'Productive follow-up session with Williams Healthcare Systems. Main discussion centered on Our developers are spending 30% of their time just writing boilerplate SQL and CREATE scripts.. Robert Williams mentioned this has been a pain point for over a year. Williams Healthcare Systems team receptive to our approach. Building momentum. Scheduling reference call with similar Finance customer.', NULL, '2026-01-20T09:59:14.148318', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39746, 10942, 34, 'Continued evaluation discussions with Robert Williams. The team is struggling with Our developers are spending 30% of their time just writing boilerplate SQL and CREATE scripts., which is impacting their operations significantly. Williams Healthcare Systems team receptive to our approach. Building momentum. Next: Send detailed proposal and pricing options.', NULL, '2026-01-27T11:45:24.788353', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39747, 10942, 34, 'Awaiting callback from Robert Williams to confirm scope.', NULL, '2026-01-27T23:19:23.651242', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39748, 10942, 34, 'Productive follow-up session with Williams Healthcare Systems. The team is struggling with Our developers are spending 30% of their time just writing boilerplate SQL and CREATE scripts., which is impacting their operations significantly. Positive vibes from the meeting. Robert Williams supportive. Next: Send detailed proposal and pricing options.', NULL, '2026-02-05T09:09:00.905954', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39749, 10942, 34, 'Meeting confirmed for next week.', NULL, '2026-02-20T21:45:55.542064', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39750, 10942, 34, 'Sent ROI calculator to Robert Williams.', NULL, '2026-02-23T18:45:37.579151', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39751, 10942, 34, 'Proposal sent to Williams Healthcare Systems.', NULL, '2026-03-07T20:20:34.346587', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39752, 10942, 34, 'Confirmed meeting for next week.', NULL, '2026-03-10T01:05:27.210233', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39753, 10942, 34, 'Extended call with Robert Williams at Williams Healthcare Systems covering their Finance infrastructure.

**Call Summary**
Productive discussion covering their Schema Design requirements. Robert Williams led the conversation with clear priorities around solving Our developers are spending 30% of their time just writing boilerplate SQL and CREATE scripts.. The team was engaged and asked detailed questions about how CodeCraft DevKit supports Visually create, modify, and manage your database schemas using an intuitive drag-and-drop interface. This simplifies the design process, promotes collaboration between developers and DBAs, and automatically generates migration scripts, reducing errors and speeding up development cycles..

**Next Steps**
1. Send final proposal with negotiated terms
2. Schedule contract review with Williams Healthcare Systems''s legal team
3. Prepare implementation timeline and resource plan
4. Robert Williams to get final budget approval from leadership
5. Target close date: End of month

_Deal: $45814 | Stage: late | Champion: Robert Williams_', NULL, '2026-03-30T06:04:34.116331', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39754, 10942, 34, 'Waiting on Williams Healthcare Systems decision.', NULL, '2026-04-01T05:32:21.870066', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39755, 10942, 34, 'Good call with Robert Williams today.', NULL, '2026-04-03T18:08:45.559465', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39756, 10942, 34, 'Scheduled callback window; expecting response this week.', NULL, '2026-04-19T11:38:19.021112', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (39757, 10942, 34, 'CLOSED WON!', NULL, '2026-04-19T11:38:19.021112', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40095, 10967, 32, 'Introductory call with Lisa Johnson to understand their needs. Main discussion centered on We need a 15-minute response time for P1 issues, not ''best effort'' from the community.. Lisa Johnson mentioned this has been a pain point for over a year. Meeting went as expected. Following standard sales process. Setting up intro call with our solutions architect.', NULL, '2025-10-21T00:00:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40096, 10967, 32, 'Comprehensive review session with Lisa Johnson regarding TitanDB Enterprise implementation.

**Call Summary**
Comprehensive call with Lisa Johnson and two other stakeholders from their technical team. Main focus was understanding how TitanDB Enterprise handles We need a 15-minute response time for P1 issues, not ''best effort'' from the community. in the context of their Enterprise-Class Support initiative. Good energy throughout the session.

**Target Use Cases**
Key use cases driving this evaluation at Garcia Education Co:

1. **Enterprise-Class Support**
   - Gain peace of mind with our 24/7 global support team, offering a 15-minute response time for critical issues. Our expert engineers provide proactive guidance and rapid troubleshooting, ensuring your production environments remain stable and minimizing the business impact of any unforeseen problems.
   - Critical for their Education operations. Current workaround involves manual processes that don''t scale.
   - Lisa Johnson''s team has been pushing for a solution here for 6+ months.

2. **Performance and Scalability**
   - Effortlessly scale your database both vertically (adding more power) and horizontally (adding more nodes) as your data grows. TitanDB''s elastic architecture ensures you can meet future demand without costly re-platforming, providing a smooth growth path from a single server to a globally distributed cluster.
   - Secondary priority but equally important for their long-term roadmap.
   - Would consolidate multiple point solutions they currently maintain.

**Connection to Pain Points:** Successfully implementing Enterprise-Class Support would directly address We need a 15-minute response time for P1 issues, not ''best effort'' from the community., which is their biggest operational challenge.

**Competitive Landscape**
Competition includes **Competitor A** (incumbent) and **Competitor B** (also evaluating). We''re differentiated on:
- Native support for their Education workflows
- More flexible pricing model
- Faster time to value

They had a bad experience with Competitor B previously - opportunity to capitalize.

_Deal: $85288 | Stage: early | Champion: Lisa Johnson_', NULL, '2025-10-27T17:39:19.797683', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40097, 10967, 32, 'Proposal sent to Garcia Education Co.', NULL, '2025-11-12T01:00:11.814214', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40098, 10967, 32, 'Demo went well with Garcia Education Co. Lisa Johnson was engaged, especially around the We need a 15-minute response time for P1 issues, not ''best effort'' from the community. solution. They want to see a POC proposal.', NULL, '2025-11-29T02:50:06.409878', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40099, 10967, 32, 'Follow-up call with Lisa Johnson. They''ve shared TitanDB Enterprise with their VP. Main concerns are around We need a 15-minute response time for P1 issues, not ''best effort'' from the community.. Addressing in next meeting.', NULL, '2025-12-03T19:01:44.103358', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40100, 10967, 32, 'Left VM for Lisa Johnson.', NULL, '2025-12-11T10:09:17.571685', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40101, 10967, 32, 'Waiting for Garcia Education Co decision.', NULL, '2026-01-01T01:10:03.203195', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40102, 10967, 32, 'Pre-decision meeting with Lisa Johnson and procurement. Deep dive into We need a 15-minute response time for P1 issues, not ''best effort'' from the community. and We only find out about a database problem when our customers call to complain.. Their current workaround is manual and error-prone. Good engagement from Lisa Johnson. They see the potential. Preparing executive summary for their leadership.', NULL, '2026-01-03T02:32:36.397686', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40103, 10967, 32, 'Call with Lisa Johnson at Garcia Education Co. Discussed We need a 15-minute response time for P1 issues, not ''best effort'' from the community. and next steps. Following up with additional materials.', NULL, '2026-01-13T15:35:29.444837', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40251, 10979, 44, 'Introductory call with Lisa Miller to understand their needs. The team is struggling with data management challenges, which is impacting their operations significantly. Standard evaluation process. Brown Education Group doing due diligence. Following up with Neuron Canvas overview deck and case studies.', NULL, '2025-10-21T14:43:00.038468', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40252, 10979, 44, 'Kicked off the evaluation process with Brown Education Group. Main discussion centered on data management challenges. Lisa Miller mentioned this has been a pain point for over a year. Lisa Miller professional and thorough in their questions. Next: Schedule technical demo with their engineering team.', NULL, '2025-10-24T01:54:53.755874', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40253, 10979, 44, 'Sent case study as requested.', NULL, '2025-11-02T19:06:59.932390', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40254, 10979, 44, 'Extended call with Lisa Miller at Brown Education Group covering their Healthcare infrastructure.

**Call Summary**
Productive discussion covering their core Healthcare requirements. Lisa Miller led the conversation with clear priorities around solving data management challenges. The team was engaged and asked detailed questions about our approach.

**Next Steps**
1. Prepare custom demo addressing key requirements
2. Schedule reference call with similar Healthcare customer
3. Send preliminary pricing and packaging options
4. Lisa Miller to arrange meeting with their VP of Engineering

**Technical Requirements**
- HIPAA compliance certification
- HL7/FHIR integration support
- Audit logging and compliance reporting

_Deal: $73302 | Stage: middle | Champion: Lisa Miller_', NULL, '2025-11-23T03:59:46.985325', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40255, 10979, 44, 'Quick check-in - all on track.', NULL, '2025-12-14T04:42:08.056740', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40256, 10979, 44, 'Negotiation call with Lisa Miller and their procurement. Working through volume discount structure for $73302 deal.', NULL, '2025-12-21T13:25:01.433066', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40257, 10979, 44, 'Final technical review with Lisa Miller and their team. Key issue raised: data management challenges. They''ve tried other solutions but none addressed their Healthcare requirements. Positive vibes from the meeting. Lisa Miller supportive. Scheduling closing call for end of week.', NULL, '2025-12-25T20:50:59.366090', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (40258, 10979, 44, 'Call with Lisa Miller at Brown Education Group. Discussed data management challenges and next steps. Following up with additional materials.', NULL, '2026-01-07T11:47:10.435002', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41007, 9678, 50, 'Call with Emily Miller at Johnson Retail Inc: Client discussed the following challenges:
1. We need our engineers to be more self-sufficient and less reliant on a few ''gurus'' on the team.
2. We don''t need a different version of the software, we just need to know someone has our back.

Proposed OS Guardian Support as a solution to address these needs.', 'internal', '2026-04-18T02:26:05', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41022, 11139, 45, 'Customer discussed the following challenges:
1. Our team is burned out from repetitive, manual, ''toil'' tasks.

Proposed Synapse AIOps as a solution to address these needs.', 'internal', '2026-04-19T23:54:59', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41072, 11169, 5, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'meeting', '2026-04-19T12:43:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41106, 11188, 8, 'Customer covered the following challenges:
1. We need a tool like a ''CPU profiler'' for our code, but for our database.
2. We think we have a locking problem, but we can''t see which sessions are blocking other sessions.

Proposed ClarityDB Guardian as a solution to address these needs. Lisa Davis requested additional information.', 'call', '2026-04-19T23:17:50', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41111, 11190, 43, 'Account expressed interest in ClarityDB Guardian for their data infrastructure needs. Scheduled follow-up call for next steps.', 'meeting', '2026-04-19T15:49:53', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41240, 2222, 16, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'email', '2026-03-31T19:48:24', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41387, 11337, 40, 'Customer discussed the following challenges:
1. We want to do ''database-as-code,'' but we have no tools to support it.

Proposed ClarityDB Guardian as a solution to address these needs.', 'email', '2026-04-19T05:49:51', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41421, 11360, 20, 'Client discussed the following challenges:
1. Our developers are writing inefficient queries because they don''t understand how the database works.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-04-19T20:52:14', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41445, 6898, 43, 'Customer discussed the following challenges:
1. Our native database auditing is too performance-intensive, so we have to leave it off.
2. In cases of unautsoft, our system does not have an intrinsic capability like flight data recorder technology for post-incident analysis and evidence gathering.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-04-17T11:10:08', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41446, 10449, 10, 'Customer discussed the following challenges:
1. A vulnerability was announced, but the community patch won''t be out for weeks.

Proposed PillarDB Standard as a solution to address these needs.', 'call', '2026-04-16T08:08:03', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41561, 9613, 13, 'Customer discussed the following challenges:
1. Our ''secret sauce'' is our proprietary data. We can''t send it to a public LLM provider who might use it for training.

Proposed TitanDB Enterprise as a solution to address these needs. Will follow up with Emily Brown next week.', 'meeting', '2026-04-15T02:44:35', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41572, 11437, 9, 'Call with Jane Brown at Williams Healthcare Corp: Customer discussed the following challenges:
1. We want to ''infuse'' all our products with AI, but we don''t know where to start.

Proposed Prometheus AI Factory as a solution to address these needs.', 'internal', '2026-04-19T15:30:03', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41647, 6560, 27, 'Spoke with Sarah Smith regarding their needs: Prospect expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-04-09T15:12:56', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41652, 11473, 17, 'Customer discussed the following challenges:
1. Our ''AI'' app is a ''black box.'' We have no idea why it made a specific decision.

Proposed Prometheus AI Factory as a solution to address these needs. Scheduled follow-up call for next steps.', 'internal', '2026-04-19T23:27:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41690, 11497, 9, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-04-19T09:32:01', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41761, 11541, 25, 'Customer discussed the following challenges:
1. We can''t afford the enterprise license, but we''re willing to pay for a performance boost.

Proposed PillarDB Standard as a solution to address these needs.', 'internal', '2026-04-19T19:19:59', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41834, 11581, 33, 'Customer discussed the following challenges:
1. We have a ''phishing'' alert. Our analyst now has to manually check 5 different tools (AD, email log, firewall log) to see what happened.

Proposed Synapse AIOps as a solution to address these needs.', 'meeting', '2026-04-19T20:09:55', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41875, 11601, 46, 'Customer discussed the following challenges:
1. Our native database auditing is too performance-intensive, so we have to leave it off.

Proposed OmniConnect Proxy as a solution to address these needs.', 'internal', '2026-04-19T20:02:12', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41893, 10937, 24, 'Customer discussed the following challenges:
1. Our model was found to be ''biased'' against a certain demographic, and it''s a huge legal and PR risk.
2. We want to add a ''summarization'' feature to our app, but we don''t know how to call an LLM securely.

Proposed Prometheus AI Factory as a solution to address these needs. Scheduled follow-up call for next steps.', 'meeting', '2025-10-13T11:09:12', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41907, 11617, 47, 'Customer discussed the following challenges:
1. Our schema changes are not reviewed by a DBA before they go to production.

Proposed CodeCraft DevKit as a solution to address these needs.', 'meeting', '2026-04-19T22:48:59', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (41975, 11650, 33, 'Customer discussed the following challenges:
1. We need to know when we will hit our ''max IOPS'' on our cloud disks.
2. Our root cause analysis is just ''We restarted the server and it''s fine now.'' We never find the real problem.

Proposed ClarityDB Guardian as a solution to address these needs.', 'internal', '2026-04-19T22:45:25', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42040, 11693, 9, 'Customer reviewed the following challenges:
1. We can''t use our ''unstructured'' data (like images and text) for AI because it''s not in our warehouse.
2. It''s too hard to ''version'' our data, so we can''t reproduce our AI model training runs.

Proposed Converge Lakehouse as a solution to address these needs.', 'internal', '2026-04-19T23:22:43', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42120, 10466, 41, 'Customer discussed the following challenges:
1. We love open-source, but our CTO is worried about running our business on unsupported software.

Proposed OS Guardian Support as a solution to address these needs.', 'internal', '2026-02-12T21:18:33', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42345, 11843, 35, 'Client reviewed the following challenges:
1. We have no access to advanced troubleshooting guides or architectural white papers.

Proposed OS Guardian Support as a solution to address these needs.', 'internal', '2026-04-19T22:01:27', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42353, 9294, 45, 'Customer discussed the following challenges:
1. By the time our analysts build a report, the business opportunity has already passed.
2. Adding a new shard to our cluster is a high-risk, manual process that can cause data inconsistencies.

Proposed OmniConnect Proxy as a solution to address these needs. Scheduled follow-up call for next steps.', 'internal', '2026-04-13T07:01:03', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42388, 11860, 45, 'Customer discussed the following challenges:
1. We fixed a performance bug, but we have no way to prove it''s fixed or prevent it from regressing.
2. Our AI model is ''drifting'' in production, and its accuracy is getting worse, but we didn''t catch it.

Proposed CodeCraft DevKit as a solution to address these needs.', 'call', '2026-04-19T18:59:49', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42523, 9200, 35, 'Client discussed the following challenges:
1. Human error during a manual process (like patching) caused a major outage.

Proposed OmniConnect Proxy as a solution to address these needs.', 'call', '2026-04-16T21:34:05', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42537, 11928, 5, 'Customer reviewed the following challenges:
1. We can''t export our database diagram to share with our compliance or security teams.
2. Our data is not ''analytics-ready'' fast enough, so our business insights are delayed.

Proposed CodeCraft DevKit as a solution to address these needs. Action items documented and assigned.', 'email', '2026-04-19T22:36:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42567, 10803, 7, 'Customer discussed the following challenges:
1. We have a team of ''citizen developers,'' but they don''t have the tools to build AI apps.

Proposed Neuron Canvas as a solution to address these needs.', 'email', '2025-09-05T10:37:34', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42699, 11996, 31, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs. Action items documented and assigned.', 'email', '2026-04-19T21:34:05', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42731, 12014, 50, 'Account expressed interest in Synapse AIOps for their data infrastructure needs.', 'call', '2026-04-19T07:10:40', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42766, 11139, 49, 'Spoke with Sarah Johnson regarding their needs: Customer went over the following challenges:
1. Our current automation is ''dumb.'' It just follows a script. It can''t handle unexpected errors.

Proposed Synapse AIOps as a solution to address these needs.', 'meeting', '2026-04-19T23:27:52', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42805, 12050, 22, 'Client discussed the following challenges:
1. We''ve hit a critical performance bug, and our internal team is completely stuck.

Proposed OS Guardian Support as a solution to address these needs. Will follow up with David Jones in the coming days.', 'internal', '2026-04-19T10:19:14', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42854, 12079, 43, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'email', '2026-04-19T18:47:27', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42863, 4242, 10, 'Customer went over the following challenges:
1. Our data scientists want to use Python and Spark, but our data is locked in a SQL-only warehouse.
2. We acquired a new company, and we have no way to query their data alongside our data.

Proposed Converge Lakehouse as a solution to address these needs. Emily Davis requested additional information.', 'email', '2026-03-23T09:29:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42879, 12095, 23, 'Meeting notes for Miller Manufacturing Inc: Account discussed the following challenges:
1. Our platformion database is down right now, and our only recourse is posting on a forum and hoping.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-04-19T18:53:20', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42899, 12104, 44, 'Client expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'email', '2026-04-19T18:11:27', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (42976, 12147, 50, 'Customer discussed the following challenges:
1. Our data ingestion for our secondary applications is too slow.

Proposed PillarDB Standard as a solution to address these needs.', 'meeting', '2026-04-19T19:14:20', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43068, 9703, 19, 'Client covered the following challenges:
1. We have no data dictionary or business glossary.

Proposed CodeCraft DevKit as a solution to address these needs.', 'internal', '2026-04-15T12:39:03', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43139, 9613, 5, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'meeting', '2026-04-17T10:51:54', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43177, 11337, 39, 'Customer covered the following challenges:
1. A developer needs to know ''how will my query perform?'' but they have to wait for a DBA to run it for them.

Proposed ClarityDB Guardian as a solution to address these needs.', 'call', '2026-04-19T05:50:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43254, 12302, 24, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'internal', '2026-04-19T22:13:51', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43302, 12014, 50, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'call', '2026-04-19T17:04:47', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43327, 12346, 4, 'Prospect expressed interest in OmniConnect Proxy for their data infrastructure needs. David Jones requested additional information.', 'internal', '2026-04-19T13:20:22', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43397, 9138, 49, 'Account discussed the following challenges:
1. Our team needs to move faster, but they are slowed down by searching for answers.
2. Our staff turnover is high, and we are constantly retraining new people from scratch.

Proposed OS Guardian Support as a solution to address these needs.', 'email', '2026-04-19T00:56:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43560, 12464, 15, 'Client went over the following challenges:
1. We need to know the ''best practices'' for tuning, not just what worked for one person.
2. We have no on-demand learning resources; all our training is ad-hoc and informal.

Proposed OS Guardian Support as a solution to address these needs. Scheduled follow-up call for next steps.', 'call', '2026-04-19T23:00:21', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43652, 11541, 37, 'Customer discussed the following challenges:
1. We''re a small-to-medium business and we need professional support that fits our budget.

Proposed PillarDB Standard as a solution to address these needs.', 'meeting', '2026-04-19T19:28:40', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43672, 12527, 48, 'Discussion with Brown Retail Inc team: Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'meeting', '2026-04-19T22:28:57', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43711, 12546, 37, 'Prospect expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'meeting', '2026-04-19T21:44:13', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43712, 12547, 43, 'Customer discussed the following challenges:
1. A bad database deployment (e.g., a schema change) is hard to roll back.

Proposed ClarityDB Guardian as a solution to address these needs. Williams Education Group team seems very interested.', 'call', '2026-04-19T15:49:30', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43768, 12577, 19, 'Customer talked about the following challenges:
1. We need to budget for 2026, and we have no idea how much our database costs will grow.

Proposed ClarityDB Guardian as a solution to address these needs.', 'internal', '2026-04-19T17:15:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43909, 8501, 7, 'Customer covered the following challenges:
1. The database is spending more CPU on connection setup/teardown than on running queries.

Proposed OmniConnect Proxy as a solution to address these needs. Will follow up with Lisa Johnson next week.', 'email', '2026-04-16T04:10:12', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (43911, 10466, 16, 'Customer talked about the following challenges:
1. We love open-source, but our CTO is worried about running our business on unsupported software.

Proposed OS Guardian Support as a solution to address these needs.', 'internal', '2026-03-15T10:26:52', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44124, 12741, 43, 'Client expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'internal', '2026-04-19T21:59:08', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44222, 11693, 19, 'Client went over the following challenges:
1. There''s no ''single source of truth'' for our AI features and our BI reports, so they give different answers.
2. Our competitors are reacting to market changes in seconds, and we''re reacting in days.

Proposed Converge Lakehouse as a solution to address these needs.', 'meeting', '2026-04-19T21:41:03', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44228, 11541, 25, 'Customer discussed the following challenges:
1. Our internal tools are critical to our productivity, but they don''t get the same budget as customer-facing apps.
2. Our team is spending time trying to find workarounds for bugs instead of building features.

Proposed PillarDB Standard as a solution to address these needs.', 'call', '2026-04-19T13:45:23', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44272, 4242, 3, 'Account discussed the following challenges:
1. Our business leaders are making ''gut feel'' decisions because they can''t get the data they need.
2. We have ''data silos''—our BI team uses the warehouse, and our AI team uses the lake, and they''re looking at different data.

Proposed Converge Lakehouse as a solution to address these needs.', 'internal', '2026-04-07T13:46:19', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44287, 12806, 13, 'Discussion with Miller Technology Systems team: Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'email', '2026-04-19T15:20:59', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44319, 12824, 5, 'Client discussed the following challenges:
1. Our team needs to move faster, but they are slowed down by searching for answers.
2. We love open-source, but our CTO is worried about running our business on unsupported software.

Proposed OS Guardian Support as a solution to address these needs.', 'meeting', '2026-04-19T16:25:18', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44391, 8130, 49, 'Customer discussed the following challenges:
1. We need to generate millions of rows of realistic-looking fake data for testing.
2. Writing complex, 500-line stored procedures in a plain text editor is painful.

Proposed CodeCraft DevKit as a solution to address these needs.', 'email', '2026-04-13T08:42:58', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44411, 12879, 11, 'Account discussed the following challenges:
1. A bad database deployment (e.g., a schema change) is hard to roll back.
2. We''re launching a new marketing campaign, and we have no idea if the database can handle the 5x traffic increase.

Proposed ClarityDB Guardian as a solution to address these needs.', 'call', '2026-04-19T06:22:26', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44470, 11693, 25, 'Customer went over the following challenges:
1. Our data is ''born in real-time'' (e.g., clickstreams), but it''s ''dead'' by the time our analysts see it.

Proposed Converge Lakehouse as a solution to address these needs.', 'call', '2026-04-19T22:57:25', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44501, 12927, 20, 'Discussion with Davis Manufacturing Group team: Customer discussed the following challenges:
1. We want to ''approve'' a dangerous action (like ''failover production'') from within chat, but we can''t.

Proposed Synapse AIOps as a solution to address these needs.', 'call', '2026-04-19T12:23:36', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44520, 12939, 46, 'Call with Robert Garcia at Smith Technology LLC: Customer discussed the following challenges:
1. Our investors are asking about our business continuity plan, and ''community support'' isn''t a good answer.
2. We need to replicate data to other systems, but the open-source replication is not compatible.

Proposed OS Guardian Support as a solution to address these needs.', 'internal', '2026-04-19T13:39:02', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44600, 10803, 50, 'Account discussed the following challenges:
1. Our AI projects fail because the ''business'' and ''IT'' are not aligned.
2. Our business has a great idea for an AI app, but our developer backlog is 12 months long.

Proposed Neuron Canvas as a solution to address these needs.', 'email', '2025-10-12T20:59:57', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44618, 12995, 33, 'Customer discussed the following challenges:
1. We want to automate simple tasks, but our current tools require us to be expert programmers.
2. We want our HR team to build an ''AI Onboarding Buddy'' for new hires, but they have no technical skills.

Proposed Neuron Canvas as a solution to address these needs. Jones Technology Solutions team seems very interested.', 'email', '2026-04-19T07:34:46', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44625, 13001, 18, 'Client discussed the following challenges:
1. We need a vendor to certify that our database is secure and patched.

Proposed Neuron Canvas as a solution to address these needs. Action items documented and assigned.', 'meeting', '2026-04-19T18:55:48', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (44687, 13040, 5, 'Customer expressed interest in TitanDB Enterprise for their data infrastructure needs.', 'email', '2026-04-19T06:07:26', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45027, 10730, 43, 'Account discussed the following challenges:
1. We have no visual way to look at our database schema; we''re just reading CREATE TABLE statements.
2. Onboarding a new developer takes forever because they can''t understand our complex data model.

Proposed CodeCraft DevKit as a solution to address these needs.', 'internal', '2026-02-17T12:15:55', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45219, 8130, 29, 'Spoke with Robert Davis regarding their needs: Customer discussed the following challenges:
1. We have no way to compare the schema in ''dev'' vs. ''prod'' to see what''s different.

Proposed CodeCraft DevKit as a solution to address these needs.', 'meeting', '2026-04-15T09:41:56', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45252, 8739, 43, 'Client expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'meeting', '2026-04-13T13:04:27', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45265, 7207, 19, 'Prospect expressed interest in Neuron Canvas for their data infrastructure needs.', 'internal', '2026-04-13T13:30:38', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45268, 13330, 42, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'internal', '2026-04-19T12:13:06', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45370, 13380, 25, 'Session notes for Jones Healthcare Inc: Customer discussed the following challenges:
1. Our data is in a complex data warehouse, and only 3 people in the company know how to query it.
2. We want our HR team to build an ''AI Onboarding Buddy'' for new hires, but they have no technical skills.

Proposed Neuron Canvas as a solution to address these needs.', 'call', '2026-04-19T08:40:21', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45424, 13410, 8, 'Client expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-04-19T23:36:35', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45475, 12104, 48, 'Customer expressed interest in OmniConnect Proxy for their data infrastructure needs.', 'email', '2026-04-19T23:30:10', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45504, 13455, 7, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'meeting', '2026-04-19T16:42:37', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45677, 11693, 46, 'Customer discussed the following challenges:
1. We can''t audit who has accessed our data in the lake.

Proposed Converge Lakehouse as a solution to address these needs.', 'meeting', '2026-04-19T22:19:59', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45712, 11497, 50, 'Customer covered the following challenges:
1. Our developers are busy on our core solution; they don''t have time to build these ''nice-to-have'' AI features.

Proposed Neuron Canvas as a solution to address these needs.', 'meeting', '2026-04-19T12:43:14', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45825, 13615, 16, 'Client discussed the following challenges:
1. We want a database that ''just works'' with our existing environment.

Proposed PillarDB Standard as a solution to address these needs.', 'meeting', '2026-04-19T23:59:04', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45874, 7207, 20, 'Customer discussed the following challenges:
1. We don''t have enough skilled security analysts, and they are burned out.

Proposed Prometheus AI Factory as a solution to address these needs.', 'meeting', '2026-04-14T01:59:54', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45948, 11843, 35, 'Customer discussed the following challenges:
1. We have no access to advanced troubleshooting guides or architectural white papers.

Proposed OS Guardian Support as a solution to address these needs. Johnson Manufacturing LLC team seems very interested.', 'internal', '2026-04-19T23:59:32', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (45949, 9826, 23, 'Follow-up with Michael Williams: Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'call', '2026-04-17T15:36:40', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46013, 13707, 8, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs. Scheduled follow-up call for next steps.', 'call', '2026-04-19T22:32:46', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46097, 13748, 3, 'Meeting notes for Davis Education Corp: Customer covered the following challenges:
1. We have 100 unused indexes that are just slowing down our writes.
2. We can''t set ''dynamic'' alerts. Our ''normal'' CPU at 3 PM is 80%, but at 3 AM it''s 10%. We need alerts that understand this.

Proposed ClarityDB Guardian as a solution to address these needs.', 'meeting', '2026-04-19T19:35:23', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46265, 13835, 2, 'Account reviewed the following challenges:
1. Our analytics are all ''batch-based.'' We have no ''real-time'' capabilities.

Proposed Converge Lakehouse as a solution to address these needs.', 'call', '2026-04-19T10:38:06', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46447, 10730, 9, 'Discussion with Garcia Education Systems team: Prospect discussed the following challenges:
1. It''s hard to refactor our database because we don''t understand the impact of a change.

Proposed CodeCraft DevKit as a solution to address these needs.', 'meeting', '2026-02-01T01:51:06', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46455, 11928, 35, 'Customer reviewed the following challenges:
1. Our ''release process'' is one person staring at 10 different dashboards for 30 minutes after a deploy.
2. We''re designing our database in a spreadsheet, which is absurd.

Proposed CodeCraft DevKit as a solution to address these needs.', 'meeting', '2026-04-20T02:27:36', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46484, 13380, 9, 'Client discussed the following challenges:
1. Our BI dashboards are too ''rigid.'' I can''t ''double-click'' and ''ask a follow-up question''.

Proposed Neuron Canvas as a solution to address these needs. Will follow up with Michael Jones next week.', 'internal', '2026-04-19T08:59:51', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46494, 9678, 22, 'Customer discussed the following challenges:
1. Our developers are writing SELECT * queries instead of using the right indexes.

Proposed CodeCraft DevKit as a solution to address these needs.', 'call', '2026-04-19T12:02:12', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46632, 14022, 26, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'meeting', '2026-04-19T19:50:45', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46682, 14042, 23, 'Customer discussed the following challenges:
1. We need to pull data from Salesforce and put it into a Google Sheet every day, and someone is doing this by hand.

Proposed Synapse AIOps as a solution to address these needs.', 'internal', '2026-04-19T20:02:37', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46717, 14060, 8, 'Customer discussed the following challenges:
1. Our ''data governance'' policy is a 50-page Word document that nobody reads.

Proposed CodeCraft DevKit as a solution to address these needs.', 'internal', '2026-04-19T05:49:54', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46788, 14102, 27, 'Account expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'internal', '2026-04-19T18:33:10', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46851, 11650, 17, 'Customer discussed the following challenges:
1. I have 5,000 alerts in my inbox, and 99% of them are just ''CPU > 80% for 5 mins''. It''s just noise.

Proposed ClarityDB Guardian as a solution to address these needs.', 'internal', '2026-04-19T23:55:43', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (46920, 9138, 8, 'Prospect reviewed the following challenges:
1. The public documentation is good for ''hello world,'' but not for our complex platformion problem.
2. We need to know the ''best practices'' for tuning, not just what worked for one person.

Proposed OS Guardian Support as a solution to address these needs. Sent proposal documentation via email.', 'internal', '2026-04-17T09:44:44', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47051, 9703, 12, 'Customer discussed the following challenges:
1. Our ''performance testing'' is just one person manually clicking around the app.
2. Onboarding a new developer takes forever because they can''t understand our complex data model.

Proposed CodeCraft DevKit as a solution to address these needs.', 'meeting', '2026-04-12T19:46:08', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47127, 7207, 10, 'Customer discussed the following challenges:
1. We want to use generative AI, but our company policy forbids sending any customer data to a public, third-party API.
2. We''re afraid of ''vendor lock-in'' with a single public AI provider.

Proposed Prometheus AI Factory as a solution to address these needs.', 'email', '2026-04-15T20:18:58', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47170, 7207, 50, 'Prospect went over the following challenges:
1. Our data quality is poor, so our AI model''s accuracy is poor. ''Garbage in, garbage out''.

Proposed Prometheus AI Factory as a solution to address these needs.', 'email', '2026-04-15T07:31:21', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47195, 14298, 40, 'Account covered the following challenges:
1. We need to scale our database, but the only option involves months of downtime and data migration.

Proposed TitanDB Enterprise as a solution to address these needs.', 'meeting', '2026-04-19T18:42:09', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47196, 14299, 48, 'Client expressed interest in Neuron Canvas for their data infrastructure needs.', 'email', '2026-04-19T12:10:05', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47227, 3140, 48, 'Customer discussed the following challenges:
1. We need a reliable database for our CMS, but we don''t need 24/7, 15-minute response.

Proposed PillarDB Standard as a solution to address these needs. Will follow up with Jane Davis next week.', 'email', '2026-04-08T11:10:03', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47458, 2222, 48, 'Spoke with Lisa Williams regarding their needs: Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'internal', '2026-03-11T07:20:59', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47545, 8136, 43, 'Customer reviewed the following challenges:
1. We''re not sure if our database backups are actually working correctly.

Proposed Synapse AIOps as a solution to address these needs.', 'call', '2026-04-19T08:58:41', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47610, 14299, 28, 'Customer expressed interest in Neuron Canvas for their data infrastructure needs.', 'email', '2026-04-19T15:08:49', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47632, 8628, 4, 'Customer discussed the following challenges:
1. Our application team can deploy code 10 times a day, but our database team deploys once a quarter. They are the bottleneck.
2. We can''t see ''internal'' database activity, like vacuuming, flushing, or log writes.

Proposed ClarityDB Guardian as a solution to address these needs.', 'call', '2026-04-18T09:50:41', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47739, 14575, 40, 'Prospect discussed the following challenges:
1. We have no on-demand learning resources; all our training is ad-hoc and informal.
2. We keep ''rediscovering'' solutions to problems our team has already solved.

Proposed OS Guardian Support as a solution to address these needs.', 'call', '2026-04-19T21:33:00', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47745, 14578, 17, 'Customer discussed the following challenges:
1. During an incident, our ''war room'' is just a chaotic Slack channel with 50 people yelling and pasting screenshots.
2. I''m a manager, and I need to get a status report, but I have to file a ticket and wait for an engineer to run it.

Proposed Synapse AIOps as a solution to address these needs.', 'meeting', '2026-04-19T19:53:32', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47783, 9460, 34, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'internal', '2026-04-13T03:04:39', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (47927, 7542, 12, 'Customer talked about the following challenges:
1. Our developers are complaining that their test environments are too slow, which slows down development.
2. The open-source drivers are unreliable and cause intermittent application errors.

Proposed PillarDB Standard as a solution to address these needs. Miller Retail Systems team seems very interested.', 'meeting', '2026-04-10T13:03:11', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (48163, 10727, 11, 'Customer discussed the following challenges:
1. We can''t ingest and query our IoT sensor data fast enough.
2. Our warehouse and our lake are constantly out of sync, leading to conflicting reports.

Proposed Converge Lakehouse as a solution to address these needs. Will follow up with Robert Brown next week.', 'meeting', '2025-12-18T17:23:54', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (48347, 11473, 49, 'Discussion with Johnson Education Systems team: Account discussed the following challenges:
1. We want to build an AI app, but our security team gave us a 100-item checklist, and we''re overwhelmed.

Proposed Prometheus AI Factory as a solution to address these needs.', 'meeting', '2026-04-19T11:51:54', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (48531, 14952, 35, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs.', 'meeting', '2026-04-19T16:56:57', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (48628, 15007, 28, 'Customer expressed interest in ClarityDB Guardian for their data infrastructure needs.', 'call', '2026-04-19T16:38:50', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (48712, 8136, 38, 'Customer expressed interest in Synapse AIOps for their data infrastructure needs. Sent proposal documentation via email.', 'meeting', '2026-04-10T17:15:01', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (48716, 7542, 33, 'Follow-up with Michael Miller: Customer covered the following challenges:
1. We don''t need 15-minute response times, but we can''t wait 3 days for a forum reply.
2. We need validated, tested bugfixes, not community-submitted patches.

Proposed PillarDB Standard as a solution to address these needs.', 'call', '2026-04-16T00:11:58', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (48736, 11843, 41, 'Customer discussed the following challenges:
1. Our data ingestion for our secondary applications is too slow.

Proposed OS Guardian Support as a solution to address these needs.', 'internal', '2026-04-19T23:57:13', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (49052, 12577, 9, 'Customer talked about the following challenges:
1. We want our CI/CD pipeline to automatically fail if a new commit introduces a query that''s 50% slower.

Proposed ClarityDB Guardian as a solution to address these needs.', 'meeting', '2026-04-19T10:25:11', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (49265, 11473, 43, 'Customer discussed the following challenges:
1. We''re afraid of the ''cost'' and ''complexity'' of building an AI platform.

Proposed Prometheus AI Factory as a solution to address these needs. Will follow up with Emily Williams next week.', 'call', '2026-04-19T16:46:07', NULL, NULL, NULL, NULL);
INSERT INTO sales_demo_app.sales_notes (note_id, order_id, salesperson_id, note_text, note_type, created_at, use_case_mentioned, sentiment, product_name, use_case) VALUES (49660, 9174, 6, 'Customer reviewed the following challenges:
1. People are storing sensitive PII data in plain text in ''notes'' fields.

Proposed CodeCraft DevKit as a solution to address these needs.', 'call', '2026-04-18T07:31:59', NULL, NULL, NULL, NULL);


-- Reset sequences to past max to keep new inserts conflict-free.
SELECT setval('sales_demo_app.salespeople_salesperson_id_seq', (SELECT MAX(salesperson_id) FROM sales_demo_app.salespeople));
SELECT setval('sales_demo_app.customers_customer_id_seq', (SELECT MAX(customer_id) FROM sales_demo_app.customers));
SELECT setval('sales_demo_app.products_product_id_seq', (SELECT MAX(product_id) FROM sales_demo_app.products));
SELECT setval('sales_demo_app.sales_orders_order_id_seq', (SELECT MAX(order_id) FROM sales_demo_app.sales_orders));
SELECT setval('sales_demo_app.sales_notes_note_id_seq', (SELECT MAX(note_id) FROM sales_demo_app.sales_notes));

COMMIT;