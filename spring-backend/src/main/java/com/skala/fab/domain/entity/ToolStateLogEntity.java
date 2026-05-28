package com.skala.fab.domain.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "tool_state_log")
public class ToolStateLogEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String runId;
    private String toolGroup;
    private String toolId;
    private String state;
    private Double stateChangeTime;
    private String setupName;
    private String lotId;
    private String reason;
    private Integer idleUnits;
    private Integer runUnits;
    private Integer setupUnits;
    private Integer downPmUnits;
    private Integer downBmUnits;
}
