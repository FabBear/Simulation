package com.skala.fab.domain.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "lot_release")
public class LotReleaseEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String productName;
    private String routeName;
    private String lotType;
    private Integer priority;
    private String isSuperHotLot;
    private Integer wafersPerLot;
    private String startDate;
    private String dueDate;
    private String releaseDist;
    private Double releaseInterval;
    private String releaseUnit;
    private Integer lotsPerRelease;
}
