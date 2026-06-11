package com.skala.fab.domain.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "setup_info_final")
public class SetupInfoEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String setupGroup;
    private String fromSetup;
    private String toSetup;
    private Double setupTime;
    private String setupUnit;
    private Integer minRunLength;
}
