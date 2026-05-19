package com.skala.fab.domain.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "breakdown_event")
public class BreakdownEventEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String eventName;
    private String scope;
    private String targetName;
    private String ttfDist;
    private Double mttfMean;
    private String mttfUnit;
    private String ttrDist;
    private Double mttrMean;
    private String mttrUnit;
    private String foaDist;
    private Double foaMean;
    private String foaUnit;
}
