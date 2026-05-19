package com.skala.fab.domain.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "lot_event_log")
public class LotEventLogEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String runId;
    private String lotId;
    private String product;
    private String routeId;
    private Integer stepSeq;
    private String toolGroup;
    private String toolId;
    private String eventType;
    private Double eventTime;
    private String detail1;
    private String detail2;
}
