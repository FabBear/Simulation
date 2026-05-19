package com.skala.fab.domain.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "toolgroup")
public class ToolGroupEntity {
    @Id
    @Column(name = "toolgroup_name")
    private String toolgroupName;
    private Integer numTools;
    private String location;
    private Boolean isCascading;
    private Boolean isBatching;
    private String batchCriterion;
    private String batchUnit;
    private Double loadingTime;
    private Double unloadingTime;
    private String dispatchRule;
    private String ranking1;
    private String ranking2;
    private String ranking3;
    private String toolWakeupRanking;
}
