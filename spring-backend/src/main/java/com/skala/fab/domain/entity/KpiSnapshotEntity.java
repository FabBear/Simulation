package com.skala.fab.domain.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.Immutable;

/**
 * Read-only mapping to {@code kpi_snapshot} VIEW (V6 UNION of kpi_fab/process/toolgroup/tool).
 * For writes use level-specific tables; see docs/BACKEND_HANDOFF_KPI_V6.md.
 */
@Immutable
@Entity
@Table(name = "kpi_snapshot")
public class KpiSnapshotEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String runId;
    private Double snapshotTime;
    private String level;
    private String scope;
    private String kpiName;
    private Double value;
    private Integer windowMinutes;
    private Double numerator;
    private Double denominator;
    private String meta;
}
