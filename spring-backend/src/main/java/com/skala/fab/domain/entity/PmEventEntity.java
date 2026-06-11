package com.skala.fab.domain.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "pm_event")
public class PmEventEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String pmName;
    private String targetToolGroup;
    private String pmType;
    private Double mtbf;
    private String mtbfUnit;
    private Double durationMean;
    private Double durationOffset;
    private String durationDist;
    private String durationUnit;
    private Double firstOccurrence;
    private String foaDist;
    private String foaUnit;
}
