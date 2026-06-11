package com.skala.fab.domain.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;

@Entity
@Table(name = "process_step")
@IdClass(ProcessStepId.class)
public class ProcessStepEntity {
    @Id
    @Column(name = "route_id")
    private String routeId;

    @Id
    @Column(name = "step_seq")
    private Integer stepSeq;

    private String stepName;
    private String area;
    private String targetToolGroup;
    private String procUnit;
    private String procTimeDist;
    private Double procTimeMean;
    private Double procTimeOffset;
    private String procTimeUnit;
    private Double cascadingInterval;
    private Integer batchMin;
    private Integer batchMax;
    private String setupId;
    private String setupPolicy;
    private Double setupTimeMean;
    private Double setupTimeOffset;
    private Integer ltlDedicationStep;
    private Double reworkProb;
    private Integer reworkTargetStep;
    private Double samplingProb;
    private Integer cqtStartStep;
    private Double cqtLimit;
    private String cqtUnit;
}
